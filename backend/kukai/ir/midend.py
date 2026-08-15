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
legacy dictionaries, accounts for every nested ``__grounded__`` marker, and
binds that output to a content-addressed :class:`GroundingContext`.  Document
identity and full revision authority remain separate evidence bits: a captured
snapshot may be identity-bound without pretending to be revision-authoritative.
"""
from __future__ import annotations

import hashlib
import json
from dataclasses import InitVar, dataclass, field
from enum import Enum
from typing import Any, Mapping

from kukai.ir.registry_base import EffectKind, ResultSpec, SYNTHETIC_FIELDS


PLAN_SCHEMA = "kir-planned-program/3"
GROUND_SCHEMA = "kir-grounded-program/3"
GROUND_CONTEXT_SCHEMA = "kir-grounding-context/1"


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


def _sha256(value: str | None, field_name: str) -> str | None:
    if value is None:
        return None
    if (not isinstance(value, str)
            or len(value) != 64
            or any(ch not in "0123456789abcdef" for ch in value)):
        raise ValueError(f"{field_name} must be a lowercase sha256 digest")
    return value


@dataclass(frozen=True, slots=True)
class GroundingContext:
    """Content-addressed evidence for the exact model read used by grounding.

    ``GroundedProgram`` used to bind only the *output* of selector resolution.
    Two documents producing the same ids/names therefore shared one
    ``ground_digest`` even though they were different execution contexts.
    This value binds the complete JSON input, a privacy-preserving document
    identity digest, and (when supplied by a revision-guarded caller) the
    revision/profile evidence.

    ``trusted_source`` names a transport boundary, not a cryptographic
    signature.  Consequently ``authoritative`` is deliberately false unless
    the trusted caller also supplies a revision-bound authoritative profile.
    Document identity alone is still useful and is exposed separately as
    ``execution_bound``; the generated C# guard rechecks that identity before
    the first mutation.
    """

    snapshot_digest: str
    document_digest: str | None
    revision_digest: str | None
    profile_digest: str | None
    source: str
    trusted_source: bool = False
    profile_authoritative: bool = False

    def __post_init__(self) -> None:
        _sha256(self.snapshot_digest, "snapshot_digest")
        _sha256(self.document_digest, "document_digest")
        _sha256(self.revision_digest, "revision_digest")
        _sha256(self.profile_digest, "profile_digest")
        if not isinstance(self.source, str) or not self.source:
            raise ValueError("grounding context needs a named source")
        if not isinstance(self.trusted_source, bool):
            raise TypeError("trusted_source must be bool")
        if not isinstance(self.profile_authoritative, bool):
            raise TypeError("profile_authoritative must be bool")
        if self.profile_authoritative and self.profile_digest is None:
            raise ValueError(
                "an authoritative profile needs a bound profile digest")

    @property
    def identity_bound(self) -> bool:
        return self.document_digest is not None

    @property
    def revision_bound(self) -> bool:
        return self.revision_digest is not None

    @property
    def execution_bound(self) -> bool:
        return self.trusted_source and self.identity_bound

    @property
    def authoritative(self) -> bool:
        return (
            self.execution_bound
            and self.revision_bound
            and self.profile_authoritative
        )

    def _unsigned_evidence(self) -> dict[str, Any]:
        return {
            "schema": GROUND_CONTEXT_SCHEMA,
            "snapshot_digest": self.snapshot_digest,
            "document_digest": self.document_digest,
            "revision_digest": self.revision_digest,
            "profile_digest": self.profile_digest,
            "source": self.source,
            "trusted_source": self.trusted_source,
            "profile_authoritative": self.profile_authoritative,
            "identity_bound": self.identity_bound,
            "revision_bound": self.revision_bound,
            "execution_bound": self.execution_bound,
            "authoritative": self.authoritative,
        }

    @property
    def context_digest(self) -> str:
        return hashlib.sha256(
            _canonical_json(self._unsigned_evidence()).encode("utf-8")
        ).hexdigest()

    def to_evidence_dict(self) -> dict[str, Any]:
        payload = self._unsigned_evidence()
        payload["context_digest"] = self.context_digest
        return payload

    @classmethod
    def from_snapshot(
        cls,
        snapshot: Any,
        *,
        source: str,
        trusted_source: bool = False,
        profile_digest: str | None = None,
        profile_authoritative: bool = False,
        revision_proof: Any = None,
    ) -> "GroundingContext":
        """Bind the exact grounder input without inventing missing evidence."""

        snapshot_json = _canonical_json(snapshot)
        snapshot_digest = hashlib.sha256(
            snapshot_json.encode("utf-8")).hexdigest()

        document_digest: str | None = None
        raw_document = (
            snapshot.get("__document_fingerprint")
            if isinstance(snapshot, Mapping) else None
        )
        if raw_document is not None:
            from kukai.ir.contracts import DocumentFingerprint

            try:
                document = DocumentFingerprint.from_dict(raw_document)
            except (TypeError, ValueError):
                # Grounding owns the typed refusal for malformed/empty legacy
                # snapshots.  Context evidence must not turn it into a panic.
                document = None
            if document is not None and document.title and (
                    document.path_name or document.project_uid):
                document_digest = document.digest

        revision_digest: str | None = None
        if revision_proof is not None:
            from kukai.ir.contracts import RevisionProof

            if not isinstance(revision_proof, RevisionProof):
                raise TypeError("revision_proof must be RevisionProof or None")
            revision_json = _canonical_json(revision_proof.to_dict())
            revision_digest = hashlib.sha256(
                revision_json.encode("utf-8")).hexdigest()

        return cls(
            snapshot_digest=snapshot_digest,
            document_digest=document_digest,
            revision_digest=revision_digest,
            profile_digest=profile_digest,
            source=source,
            trusted_source=trusted_source,
            profile_authoritative=profile_authoritative,
        )

    @classmethod
    def unbound(cls) -> "GroundingContext":
        return cls.from_snapshot(
            None,
            source="legacy_unbound",
            trusted_source=False,
        )


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
    contract_digest: str
    provenance: OpProvenance
    nested_contracts: tuple["NestedOpContract", ...]
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
        if (not isinstance(self.contract_digest, str)
                or len(self.contract_digest) != 64
                or any(ch not in "0123456789abcdef"
                       for ch in self.contract_digest)):
            raise ValueError("planned op needs a lowercase sha256 contract digest")
        if not isinstance(self.provenance, OpProvenance):
            raise TypeError("planned op provenance must be typed")
        if (not isinstance(self.nested_contracts, tuple)
                or any(not isinstance(item, NestedOpContract)
                       for item in self.nested_contracts)):
            raise TypeError("nested operation contracts must be a typed tuple")
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
        if self.op_name != "create_group" and self.nested_contracts:
            raise ValueError("only create_group can carry nested contracts")
        if self.op_name == "create_group":
            members = payload.get("members")
            if not isinstance(members, list):
                raise ValueError("create_group needs a member list")
            member_identity = [
                (item.get("id"), item.get("op"))
                for item in members if isinstance(item, dict)
            ]
            contract_identity = [
                (item.member_id, item.op_name) for item in self.nested_contracts
            ]
            if contract_identity != member_identity:
                raise ValueError(
                    "nested contracts must cover group members in exact order")
            for member, contract in zip(members, self.nested_contracts):
                if contract.payload_digest != hashlib.sha256(
                        _canonical_json(member).encode("utf-8")).hexdigest():
                    raise ValueError(
                        "nested contract payload digest disagrees with member")

    @classmethod
    def from_dict(
        cls,
        payload: dict[str, Any],
        *,
        family: OperationFamily,
        effect: EffectKind,
        result: ResultSpec,
        contract_digest: str,
        provenance: OpProvenance,
        nested_contracts: tuple["NestedOpContract", ...] = (),
    ) -> "PlannedOp":
        return cls(
            op_id=payload["id"],
            op_name=payload["op"],
            family=family,
            effect=effect,
            result=result,
            contract_digest=contract_digest,
            provenance=provenance,
            nested_contracts=nested_contracts,
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
            "contract_digest": self.contract_digest,
            "nested_contracts": [
                item.to_evidence_dict() for item in self.nested_contracts
            ],
            "provenance": self.provenance.to_dict(),
        }


@dataclass(frozen=True, slots=True)
class NestedOpContract:
    """Contract identity of one fully planned ``create_group`` member.

    The member payload already lives inside the parent operation.  The
    additional typed row binds the registry/lowering semantics under which
    that payload was validated; a changed member contract therefore changes
    the parent ``plan_digest`` even when the authored JSON does not.
    """

    member_id: str
    op_name: str
    contract_digest: str
    payload_digest: str

    def __post_init__(self) -> None:
        if not isinstance(self.member_id, str) or not self.member_id:
            raise ValueError("nested contract needs a member id")
        if not isinstance(self.op_name, str) or not self.op_name:
            raise ValueError("nested contract needs an operation name")
        _sha256(self.contract_digest, "nested contract_digest")
        _sha256(self.payload_digest, "nested payload_digest")

    @classmethod
    def from_planned_op(cls, operation: PlannedOp) -> "NestedOpContract":
        if not isinstance(operation, PlannedOp):
            raise TypeError("nested contract source must be PlannedOp")
        return cls(
            member_id=operation.op_id,
            op_name=operation.op_name,
            contract_digest=operation.contract_digest,
            payload_digest=operation.payload_digest,
        )

    def to_evidence_dict(self) -> dict[str, str]:
        return {
            "member_id": self.member_id,
            "op_name": self.op_name,
            "contract_digest": self.contract_digest,
            "payload_digest": self.payload_digest,
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


_GROUND_MARKER_KEYS = frozenset({
    "id", "name", "via", "ref", "in_emit", "category", "family_name",
    "type_name", "disambiguate_by", "rule_detail",
})
_GROUND_ID_VIAS = frozenset({
    "element_id", "name", "name+disambiguate_by", "family_type",
    "sole_entry", "sole_entry+disambiguate_by", "most_used",
    "most_used+disambiguate_by",
})
_GRAPH_OPS = frozenset({
    "create_pipe_system", "route_pipe_system", "route_duct_system",
})
_SLOPE_OPS = frozenset({"route_pipe_system", "route_duct_system"})


def _valid_ground_marker(value: Any) -> bool:
    if not (isinstance(value, dict) and set(value) == {"__grounded__"}):
        return False
    detail = value.get("__grounded__")
    if (not isinstance(detail, dict)
            or not set(detail).issubset(_GROUND_MARKER_KEYS)):
        return False
    via = detail.get("via")
    if not isinstance(via, str) or not via:
        return False
    if via == "ref":
        return (
            set(detail) == {"ref", "via"}
            and isinstance(detail.get("ref"), str)
            and bool(detail["ref"])
        )
    if via == "doc_default":
        return (
            set(detail) == {"id", "name", "via", "in_emit"}
            and detail.get("id") is None
            and detail.get("name") is None
            and detail.get("in_emit") == "__doc_default__"
        )
    identifier = detail.get("id")
    if (via not in _GROUND_ID_VIAS
            or isinstance(identifier, bool)
            or not isinstance(identifier, int)
            or not 1 <= identifier <= 0x7FFF_FFFF_FFFF_FFFF
            or (detail.get("name") is not None
                and not isinstance(detail.get("name"), str))):
        return False
    base = {"id", "name", "via"}
    if via == "family_type":
        return (
            set(detail) == base | {"category", "family_name", "type_name"}
            and all(isinstance(detail.get(name), str) and detail[name]
                    for name in ("category", "family_name", "type_name"))
        )
    if via.startswith("most_used"):
        rule = detail.get("rule_detail")
        expected = base | {"rule_detail"}
        if via.endswith("+disambiguate_by"):
            expected.add("disambiguate_by")
        return (
            set(detail) == expected
            and isinstance(rule, dict)
            and set(rule) == {"instances", "candidates", "runner_up"}
            and all(isinstance(rule[name], int) and not isinstance(
                    rule[name], bool) and rule[name] >= 0 for name in rule)
        )
    expected = set(base)
    if via.endswith("+disambiguate_by"):
        expected.add("disambiguate_by")
    return set(detail) == expected


def _valid_grounded_selector(planned: Any, grounded: Any) -> bool:
    if isinstance(planned, list):
        return (
            isinstance(grounded, list)
            and len(grounded) == len(planned)
            and all(_valid_grounded_selector(source, resolved)
                    for source, resolved in zip(planned, grounded))
        )
    if not _valid_ground_marker(grounded):
        return False
    # An omitted optional selector may be deterministically inserted by the
    # grounder.  There is no authored selector to compare in that case.
    if planned is None:
        return True
    if not isinstance(planned, dict):
        return False
    detail = grounded["__grounded__"]
    by = planned.get("by")
    if by == "element_id":
        return (
            detail.get("via") == "element_id"
            and detail.get("id") == planned.get("value")
        )
    if by == "ref":
        return (
            detail.get("via") == "ref"
            and detail.get("ref") == planned.get("value")
        )
    if by == "family_type":
        return (
            detail.get("via") == "family_type"
            and all(detail.get(name) == planned.get(name)
                    for name in ("category", "family_name", "type_name"))
        )
    disambiguator = planned.get("disambiguate_by")
    if by == "name":
        resolved_name = detail.get("name")
        wanted = planned.get("value")
        return (
            detail.get("via") == (
                "name+disambiguate_by" if disambiguator is not None else "name")
            and isinstance(resolved_name, str)
            and isinstance(wanted, str)
            and resolved_name.strip().casefold() == wanted.strip().casefold()
            and detail.get("disambiguate_by") == disambiguator
        )
    if by == "default":
        expected_vias = (
            {"sole_entry+disambiguate_by", "most_used+disambiguate_by"}
            if disambiguator is not None else
            {"doc_default", "sole_entry", "most_used"}
        )
        return (
            detail.get("via") in expected_vias
            and detail.get("disambiguate_by") == disambiguator
        )
    return False


def _refinement_error(path: str, message: str) -> ValueError:
    return ValueError(f"illegal grounding refinement at {path}: {message}")


_NO_DERIVED_ARTIFACT = object()


def _recomputed_derived_artifact(
    planned: dict[str, Any],
    key: str,
    snapshot: Any,
) -> Any:
    """Re-run the pure lowering rule for one compiler-derived artifact."""

    from kukai.ir import connect, contour, route_mep, spec

    op_name = planned["op"]
    op_spec = spec.OPS[op_name]
    diagnostics: list[Any] = []
    diameter_spec = next(
        (param for param in op_spec.params if param.name == "diameter_mm"),
        None,
    )
    diameter_bounds = (
        (diameter_spec.min_val, diameter_spec.max_val)
        if diameter_spec is not None else None
    )

    if key == "__region__":
        region_fields = [
            param.name for param in op_spec.params
            if param.kind == "region" and param.name in planned
        ]
        if len(region_fields) != 1:
            return _NO_DERIVED_ARTIFACT
        grids = (
            snapshot.get("grids", [])
            if isinstance(snapshot, Mapping) else []
        )
        try:
            result = contour.validate_region(
                planned[region_fields[0]], grids, planned["id"],
                region_fields[0], diagnostics)
        except Exception as exc:  # malformed/unavailable replay input
            raise _refinement_error(
                f"ops[{planned['id']}].__region__",
                f"region replay failed: {type(exc).__name__}",
            ) from exc
        if result is None or diagnostics:
            raise _refinement_error(
                f"ops[{planned['id']}].__region__",
                "region lowering could not be independently replayed",
            )
        return result

    if key == "__graph__" and op_name in _GRAPH_OPS:
        source = (
            route_mep.strip_slope_keys(planned)
            if op_name in _SLOPE_OPS else planned
        )
        result = connect.graph_validate(
            source,
            planned["id"],
            diagnostics,
            planned.get("diameter_mm"),
            diameter_bounds,
        )
        if result is None or diagnostics:
            raise _refinement_error(
                f"ops[{planned['id']}].__graph__",
                "graph lowering could not be independently replayed",
            )
        return result

    if key == "__slope_reqs__" and op_name in _SLOPE_OPS:
        result = route_mep.extract_slope_requirements(
            planned, planned["id"], diagnostics)
        if result is None or diagnostics:
            raise _refinement_error(
                f"ops[{planned['id']}].__slope_reqs__",
                "slope lowering could not be independently replayed",
            )
        return result

    return _NO_DERIVED_ARTIFACT


def _assert_payload_refinement(
    planned: dict[str, Any],
    grounded: dict[str, Any],
    *,
    path: str,
    grounded_by_id: Mapping[str, dict[str, Any]],
    snapshot: Any,
) -> None:
    """Prove that grounding changed only the closed lowering surface."""

    from kukai.ir import relate, spec

    if planned.get("id") != grounded.get("id") \
            or planned.get("op") != grounded.get("op"):
        raise _refinement_error(path, "operation identity changed")
    op_name = str(planned["op"])
    op_spec = spec.OPS.get(op_name)
    if op_spec is None:
        raise _refinement_error(path, "operation disappeared from registry")
    required_derived: set[str] = set()
    if any(param.kind == "region" and param.name in planned
           for param in op_spec.params):
        required_derived.add("__region__")
    if op_name in _GRAPH_OPS:
        required_derived.add("__graph__")
    if op_name in _SLOPE_OPS:
        required_derived.add("__slope_reqs__")
    missing_derived = sorted(required_derived - set(grounded))
    if missing_derived:
        raise _refinement_error(
            path, f"required lowering artifacts missing: {missing_derived}")
    if not set(planned).issubset(grounded):
        removed = sorted(set(planned) - set(grounded))
        raise _refinement_error(path, f"planned fields removed: {removed}")

    grounded_fields = {name for name, _pool, _required in op_spec.grounded}
    address_fields = relate.addressable_params(op_name)
    changed_addresses = {
        name for name in address_fields
        if name in planned
        and relate.is_address(planned[name])
        and grounded.get(name) != planned[name]
    }
    receipts = grounded.get("__address__")
    receipt_by_param: dict[str, Any] = {}
    if receipts is not None:
        if not isinstance(receipts, list):
            raise _refinement_error(path + ".__address__", "receipt is not a list")
        for row in receipts:
            if (not isinstance(row, dict)
                    or row.get("op_id") != planned["id"]
                    or not isinstance(row.get("param"), str)
                    or row["param"] in receipt_by_param):
                raise _refinement_error(
                    path + ".__address__", "receipt identity is invalid")
            receipt_by_param[row["param"]] = row.get("point_mm")
        if set(receipt_by_param) != changed_addresses:
            raise _refinement_error(
                path + ".__address__",
                "receipt does not account for exactly the changed addresses",
            )
        for name in changed_addresses:
            if grounded.get(name) != receipt_by_param[name]:
                raise _refinement_error(
                    f"{path}.{name}", "resolved point disagrees with receipt")
    elif changed_addresses:
        raise _refinement_error(path, "address changed without a receipt")

    for key, planned_value in planned.items():
        grounded_value = grounded[key]
        if grounded_value == planned_value:
            continue
        field_path = f"{path}.{key}"
        if key in grounded_fields:
            if not _valid_grounded_selector(planned_value, grounded_value):
                raise _refinement_error(
                    field_path, "declared selector did not lower to a valid marker")
            continue
        if key in changed_addresses:
            continue
        if key == "members" and op_name == "create_group":
            if (not isinstance(planned_value, list)
                    or not isinstance(grounded_value, list)
                    or len(planned_value) != len(grounded_value)):
                raise _refinement_error(
                    field_path, "member cardinality/order changed")
            for index, (planned_member, grounded_member) in enumerate(zip(
                    planned_value, grounded_value)):
                if not isinstance(planned_member, dict) or not isinstance(
                        grounded_member, dict):
                    raise _refinement_error(
                        f"{field_path}[{index}]", "member is not an object")
                _assert_payload_refinement(
                    planned_member,
                    grounded_member,
                    path=f"{field_path}[{index}]",
                    grounded_by_id={},
                    snapshot=snapshot,
                )
            continue
        raise _refinement_error(field_path, "ordinary planned value changed")

    added = set(grounded) - set(planned)
    for key in sorted(added):
        value = grounded[key]
        field_path = f"{path}.{key}"
        if key in grounded_fields:
            if not _valid_grounded_selector(None, value):
                raise _refinement_error(
                    field_path, "omitted selector gained an invalid marker")
            continue
        if key == "__address__" and changed_addresses:
            continue
        expected_derived = _recomputed_derived_artifact(
            planned, key, snapshot)
        if (expected_derived is not _NO_DERIVED_ARTIFACT
                and _canonical_json(value) == _canonical_json(
                    expected_derived)):
            continue
        # Владельцев поля спрашиваем у ВЛАСТИ (registry_base.SYNTHETIC_FIELDS),
        # а не носим их парой рядом с проверкой: пара уже разошлась однажды —
        # разбор опа о поле не знал вовсе, и группа с дверью не собиралась.
        if op_name in SYNTHETIC_FIELDS.get(key, frozenset()):
            host = planned.get("host")
            host_id = host.get("value") if isinstance(host, dict) else None
            host_op = grounded_by_id.get(host_id)
            if isinstance(host_op, dict):
                expected = {
                    name: host_op[name] for name in ("p0_mm", "p1_mm")
                    if name in host_op
                }
                if isinstance(host_op.get("arc"), dict):
                    expected["arc"] = host_op["arc"]
                if value == expected and set(expected) >= {"p0_mm", "p1_mm"}:
                    continue
        raise _refinement_error(field_path, "undeclared lowering field added")


@dataclass(frozen=True, slots=True)
class GroundedProgram:
    """Immutable exact output of grounding one :class:`PlannedProgram`.

    Parent binding fixes operation order/identity and prevents a changed
    output from retaining the same digest.  The constructor also proves the
    closed refinement surface independently of the grounder: authored values
    are immutable, while selectors, addresses and named compiler artifacts may
    change only where the registry/op contract declares that lowering.
    """

    planned: PlannedProgram
    ops: tuple[GroundedOp, ...]
    resolutions: tuple[GroundingResolution, ...]
    context: GroundingContext = field(default_factory=GroundingContext.unbound)
    ground_digest: str = ""
    verification_snapshot: InitVar[Any] = None
    selector_resolution_replayed: bool = field(init=False, default=False)
    derived_artifacts_verified: bool = field(init=False, default=False)

    def __post_init__(self, verification_snapshot: Any) -> None:
        if not isinstance(self.planned, PlannedProgram):
            raise TypeError("grounded program needs a typed parent plan")
        if (not isinstance(self.ops, tuple)
                or any(not isinstance(op, GroundedOp) for op in self.ops)):
            raise TypeError("grounded operations must be a typed tuple")
        if (not isinstance(self.resolutions, tuple)
                or any(not isinstance(item, GroundingResolution)
                       for item in self.resolutions)):
            raise TypeError("grounding resolutions must be a typed tuple")
        if not isinstance(self.context, GroundingContext):
            raise TypeError("grounded program needs typed context evidence")
        if verification_snapshot is not None:
            snapshot_digest = hashlib.sha256(
                _canonical_json(verification_snapshot).encode("utf-8")
            ).hexdigest()
            if snapshot_digest != self.context.snapshot_digest:
                raise ValueError(
                    "grounding verification snapshot disagrees with context")

        planned_identity = [
            (op.op_id, op.op_name) for op in self.planned.ops
        ]
        grounded_identity = [(op.op_id, op.op_name) for op in self.ops]
        if grounded_identity != planned_identity:
            raise ValueError(
                "grounded operations must preserve parent order and identity")

        grounded_payloads = {
            op.op_id: op.to_dict() for op in self.ops
        }
        for planned_op, grounded_op in zip(self.planned.ops, self.ops):
            _assert_payload_refinement(
                planned_op.to_dict(),
                grounded_op.to_dict(),
                path=f"ops[{planned_op.op_id}]",
                grounded_by_id=grounded_payloads,
                snapshot=verification_snapshot,
            )
        object.__setattr__(self, "derived_artifacts_verified", True)

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
        # Marker shape and authored-selector consistency are independently
        # checked above.  Pool membership/ambiguity is not reimplemented here:
        # without replaying the exact snapshot resolver, claiming that proof
        # would overstate what a content digest alone establishes.
        object.__setattr__(
            self,
            "selector_resolution_replayed",
            not self.resolutions,
        )

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
        context: GroundingContext | None = None,
        snapshot: Any = None,
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
            context=context if context is not None else GroundingContext.unbound(),
            verification_snapshot=snapshot,
        )

    def _unsigned_evidence(self) -> dict[str, Any]:
        return {
            "schema": GROUND_SCHEMA,
            "plan_digest": self.planned.plan_digest,
            "context": self.context.to_evidence_dict(),
            "validation": {
                "derived_artifacts_verified": self.derived_artifacts_verified,
                "selector_resolution_replayed": (
                    self.selector_resolution_replayed),
            },
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
