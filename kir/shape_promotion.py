"""An honest LOD-promotion seam: provisional DirectShape -> native BIM.

The module does not guess BIM meaning from a mesh and does not change the
model. It links already-verified plans: the geometric source, the author's
explicitly named intent, and a separate candidate built from native
operations. Execution, approval and an independent read of the result stay
separate facts.
"""
from __future__ import annotations

import hashlib
import json
import re
from dataclasses import dataclass
from enum import Enum
from typing import Any, Mapping, Sequence

from kir import spec
from kir.midend import PlannedOp, PlannedProgram
from kir.ops_shape import IMPERSONATION_ROUTES


SHAPE_INTENT_SCHEMA = "kir-shape-intent/1"
SHAPE_PROMOTION_SCHEMA = "kir-shape-promotion/2"
SHAPE_APPROVAL_SCHEMA = "kir-shape-approval/1"
SHAPE_READBACK_SCHEMA = "kir-shape-readback/1"
SHAPE_EVIDENCE_SCHEMA = "kir-shape-evidence/1"
_SHA256_RE = re.compile(r"[0-9a-f]{64}\Z")


class ShapePromotionError(ValueError):
    """An LOD-promotion artifact contradicts its own contract."""


class PromotionState(str, Enum):
    PROVISIONAL = "provisional"
    CANDIDATE = "candidate"
    PROMOTED = "promoted"
    RESIDUAL = "residual"


def _canonical(value: Any) -> str:
    try:
        return json.dumps(value, ensure_ascii=False, sort_keys=True,
                          separators=(",", ":"), allow_nan=False)
    except (TypeError, ValueError) as exc:
        raise ShapePromotionError(
            "shape promotion carries a non-canonical JSON value") from exc


def _sha(value: str, field: str) -> str:
    if not isinstance(value, str) or not _SHA256_RE.fullmatch(value):
        raise ShapePromotionError(f"{field} must be a lowercase SHA-256")
    return value


def _non_empty(value: str, field: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise ShapePromotionError(f"{field} must be a non-empty string")
    return value


def _json_copy(value: Mapping[str, Any], field: str) -> dict[str, Any]:
    if not isinstance(value, Mapping):
        raise ShapePromotionError(f"{field} must be an object")
    return json.loads(_canonical(dict(value)))


def _op(plan: PlannedProgram, op_id: str, field: str) -> PlannedOp:
    if not isinstance(plan, PlannedProgram):
        raise ShapePromotionError(f"{field} plan must be PlannedProgram")
    rows = [operation for operation in plan.ops if operation.op_id == op_id]
    if len(rows) != 1:
        raise ShapePromotionError(
            f"{field} op id {op_id!r} must address exactly one planned op")
    return rows[0]


def _planned_payload_hash(operation: PlannedOp) -> str:
    """The exact payload's hash from the verified plan, not the caller's claim."""

    return operation.payload_digest


def _has_capability(operation: PlannedOp, capability: tuple[str, str]) -> bool:
    ospec = spec.OPS.get(operation.op_name)
    return ospec is not None and capability in ospec.capability


def allowed_native_ops(intended_role: str) -> tuple[str, ...]:
    """Native routes from the same table the mesh refusal uses."""

    route = IMPERSONATION_ROUTES.get(intended_role)
    if route is None:
        raise ShapePromotionError(
            f"unknown intended BIM role {intended_role!r}; no native route")
    return tuple(part.strip() for part in route.split("/") if part.strip())


@dataclass(frozen=True, slots=True, init=False)
class ShapeIntent:
    """A BIM intent next to an honestly geometric source element."""

    source_plan_digest: str
    source_op_id: str
    source_op_name: str
    source_geometry_hash: str
    source_expr_hash: str | None
    intended_role: str
    _constraints_json: str

    def __init__(
        self,
        *,
        source_plan: PlannedProgram,
        source_op_id: str,
        intended_role: str,
        constraints: Mapping[str, Any] | None = None,
        source_geometry_hash: str | None = None,
        source_expr_hash: str | None = None,
    ) -> None:
        operation = _op(source_plan, source_op_id, "source")
        if not _has_capability(operation, ("create", "geometry")):
            raise ShapePromotionError(
                f"source op {operation.op_name!r} is not geometry materialization")
        if _has_capability(operation, ("create", "element")):
            raise ShapePromotionError(
                f"source op {operation.op_name!r} is already native BIM; "
                "promotion accepts only geometry-only materialization")
        allowed_native_ops(intended_role)
        object.__setattr__(self, "source_plan_digest", source_plan.plan_digest)
        object.__setattr__(self, "source_op_id",
                           _non_empty(source_op_id, "source_op_id"))
        object.__setattr__(self, "source_op_name", operation.op_name)
        payload_hash = _planned_payload_hash(operation)
        if source_geometry_hash is not None:
            supplied_hash = _sha(
                source_geometry_hash, "source_geometry_hash")
            if supplied_hash != payload_hash:
                raise ShapePromotionError(
                    "source_geometry_hash disagrees with planned source payload")
        object.__setattr__(self, "source_geometry_hash", payload_hash)
        if source_expr_hash is not None:
            source_expr_hash = _sha(source_expr_hash, "source_expr_hash")
        object.__setattr__(self, "source_expr_hash", source_expr_hash)
        object.__setattr__(self, "intended_role", intended_role)
        object.__setattr__(self, "_constraints_json",
                           _canonical(_json_copy(constraints or {},
                                                 "constraints")))

    @property
    def state(self) -> PromotionState:
        return PromotionState.PROVISIONAL

    @property
    def constraints(self) -> dict[str, Any]:
        return json.loads(self._constraints_json)

    def to_dict(self) -> dict[str, Any]:
        return {
            "schema": SHAPE_INTENT_SCHEMA,
            "state": self.state.value,
            "source_plan_digest": self.source_plan_digest,
            "source_op_id": self.source_op_id,
            "source_op_name": self.source_op_name,
            "source_geometry_hash": self.source_geometry_hash,
            "source_expr_hash": self.source_expr_hash,
            "intended_role": self.intended_role,
            "constraints": self.constraints,
        }

    @property
    def digest(self) -> str:
        return hashlib.sha256(_canonical(self.to_dict()).encode()).hexdigest()


@dataclass(frozen=True, slots=True, init=False)
class PromotionCandidate:
    """A separate native revision; on its own it replaces nothing."""

    intent: ShapeIntent
    candidate_plan_digest: str
    candidate_op_ids: tuple[str, ...]
    candidate_op_names: tuple[str, ...]
    candidate_identity_cardinalities: tuple[str, ...]

    def __init__(self, *, intent: ShapeIntent, candidate_plan: PlannedProgram,
                 candidate_op_ids: Sequence[str]) -> None:
        if not isinstance(intent, ShapeIntent):
            raise ShapePromotionError("intent must be ShapeIntent")
        if not isinstance(candidate_plan, PlannedProgram):
            raise ShapePromotionError(
                "candidate plan must be PlannedProgram")
        if candidate_plan.plan_digest == intent.source_plan_digest:
            raise ShapePromotionError(
                "candidate must be a separate planned revision")
        if isinstance(candidate_op_ids, (str, bytes)):
            raise ShapePromotionError(
                "candidate_op_ids must be a sequence, not one string")
        ids = tuple(candidate_op_ids)
        if not ids or any(not isinstance(value, str) or not value for value in ids):
            raise ShapePromotionError("candidate_op_ids must be non-empty strings")
        if len(ids) != len(set(ids)):
            raise ShapePromotionError("candidate_op_ids must not repeat")
        plan_ids = tuple(operation.op_id for operation in candidate_plan.ops)
        if ids != plan_ids:
            raise ShapePromotionError(
                "candidate_op_ids must cover the complete candidate plan "
                "in execution order")
        allowed = set(allowed_native_ops(intent.intended_role))
        operations = tuple(_op(candidate_plan, op_id, "candidate") for op_id in ids)
        for operation in operations:
            if operation.op_name not in allowed:
                raise ShapePromotionError(
                    f"{operation.op_name!r} cannot promote role "
                    f"{intent.intended_role!r}; expected {sorted(allowed)}")
            if not _has_capability(operation, ("create", "element")):
                raise ShapePromotionError(
                    f"candidate op {operation.op_name!r} is not native BIM")
        object.__setattr__(self, "intent", intent)
        object.__setattr__(self, "candidate_plan_digest",
                           candidate_plan.plan_digest)
        object.__setattr__(self, "candidate_op_ids", ids)
        object.__setattr__(self, "candidate_op_names",
                           tuple(operation.op_name for operation in operations))
        object.__setattr__(self, "candidate_identity_cardinalities", tuple(
            operation.result.identity_cardinality.value
            for operation in operations))

    @property
    def state(self) -> PromotionState:
        return PromotionState.CANDIDATE

    def to_dict(self) -> dict[str, Any]:
        return {
            "schema": SHAPE_PROMOTION_SCHEMA,
            "state": self.state.value,
            "intent_digest": self.intent.digest,
            "candidate_plan_digest": self.candidate_plan_digest,
            "candidate_op_ids": list(self.candidate_op_ids),
            "candidate_op_names": list(self.candidate_op_names),
            "candidate_identity_cardinalities": list(
                self.candidate_identity_cardinalities),
            # A candidate does not authorize its own execution: the user's
            # confirmation stays a separate, mandatory fact.
            "requires_user_approval": True,
        }

    @property
    def digest(self) -> str:
        return hashlib.sha256(_canonical(self.to_dict()).encode()).hexdigest()


@dataclass(frozen=True, slots=True, init=False)
class PromotionEvidence:
    """Linked approval/readback bytes, checked by the authority's owner.

    KIR does not authenticate the user or the Revit host. The caller passes
    ``authority_verified=True`` only after its own permission check. In
    return, this type makes it impossible to mix up the decision's object,
    the plan, the document, the commit and the actually-read ElementIds: all
    values are linked and hashed here from full records, rather than arriving
    as separate, merely plausible-looking strings.
    """

    candidate_digest: str
    approval_ref: str
    approval_evidence_hash: str
    readback_evidence_hash: str
    document_key: str
    native_element_ids: tuple[int, ...]
    _created_json: str

    def __init__(
        self,
        *,
        candidate: PromotionCandidate,
        approval_record: Mapping[str, Any],
        readback_record: Mapping[str, Any],
        authority_verified: bool,
    ) -> None:
        if not isinstance(candidate, PromotionCandidate):
            raise ShapePromotionError("evidence needs PromotionCandidate")
        if authority_verified is not True:
            raise ShapePromotionError(
                "promotion evidence authority is not verified")
        approval = _json_copy(approval_record, "approval_record")
        readback = _json_copy(readback_record, "readback_record")

        if approval.get("schema") != SHAPE_APPROVAL_SCHEMA:
            raise ShapePromotionError("approval_record has unknown schema")
        if approval.get("candidate_digest") != candidate.digest:
            raise ShapePromotionError(
                "approval_record names another promotion candidate")
        if approval.get("decision") != "approved":
            raise ShapePromotionError("approval_record is not approved")
        approval_ref = _non_empty(
            approval.get("approval_ref"), "approval_record.approval_ref")
        _non_empty(approval.get("approved_by"),
                   "approval_record.approved_by")

        if readback.get("schema") != SHAPE_READBACK_SCHEMA:
            raise ShapePromotionError("readback_record has unknown schema")
        if readback.get("candidate_digest") != candidate.digest:
            raise ShapePromotionError(
                "readback_record names another promotion candidate")
        if readback.get("candidate_plan_digest") != \
                candidate.candidate_plan_digest:
            raise ShapePromotionError(
                "readback_record names another candidate plan")
        if readback.get("transaction_status") != "Committed":
            raise ShapePromotionError(
                "readback_record has no trusted committed transaction")
        if readback.get("independent") is not True:
            raise ShapePromotionError(
                "readback_record is not an independent post-commit read")
        document_key = _non_empty(
            readback.get("document_key"), "readback_record.document_key")
        created = readback.get("created")
        if not isinstance(created, Mapping):
            raise ShapePromotionError("readback_record.created must be an object")
        if set(created) != set(candidate.candidate_op_ids):
            raise ShapePromotionError(
                "readback_record.created must cover exactly the candidate ops")

        frozen_created: dict[str, list[int]] = {}
        flattened: list[int] = []
        for op_id, cardinality in zip(
                candidate.candidate_op_ids,
                candidate.candidate_identity_cardinalities,
                strict=True):
            raw_ids = created.get(op_id)
            if (not isinstance(raw_ids, Sequence)
                    or isinstance(raw_ids, (str, bytes, bytearray))):
                raise ShapePromotionError(
                    f"readback ids for {op_id} must be a sequence")
            ids = tuple(raw_ids)
            if (any(isinstance(value, bool) or not isinstance(value, int)
                    or value <= 0 for value in ids)
                    or len(ids) != len(set(ids))):
                raise ShapePromotionError(
                    f"readback ids for {op_id} must be unique positive integers")
            if cardinality == "one" and len(ids) != 1:
                raise ShapePromotionError(
                    f"readback ids for {op_id} disagree with ONE cardinality")
            if cardinality == "many" and not ids:
                raise ShapePromotionError(
                    f"readback ids for {op_id} disagree with MANY cardinality")
            if cardinality == "none" and ids:
                raise ShapePromotionError(
                    f"readback ids for {op_id} disagree with NONE cardinality")
            if cardinality not in {"one", "many", "none"}:
                raise ShapePromotionError(
                    f"candidate {op_id} has unknown identity cardinality")
            frozen_created[op_id] = list(ids)
            flattened.extend(ids)
        if not flattened:
            raise ShapePromotionError(
                "promotion evidence contains no native Revit element")
        if len(flattened) != len(set(flattened)):
            raise ShapePromotionError(
                "one native ElementId is attributed to multiple candidate ops")

        object.__setattr__(self, "candidate_digest", candidate.digest)
        object.__setattr__(self, "approval_ref", approval_ref)
        object.__setattr__(self, "approval_evidence_hash", hashlib.sha256(
            _canonical(approval).encode()).hexdigest())
        object.__setattr__(self, "readback_evidence_hash", hashlib.sha256(
            _canonical(readback).encode()).hexdigest())
        object.__setattr__(self, "document_key", document_key)
        object.__setattr__(self, "native_element_ids", tuple(flattened))
        object.__setattr__(self, "_created_json", _canonical(frozen_created))

    @property
    def created(self) -> dict[str, list[int]]:
        return json.loads(self._created_json)

    def to_dict(self) -> dict[str, Any]:
        return {
            "schema": SHAPE_EVIDENCE_SCHEMA,
            "candidate_digest": self.candidate_digest,
            "approval_ref": self.approval_ref,
            "approval_evidence_hash": self.approval_evidence_hash,
            "readback_evidence_hash": self.readback_evidence_hash,
            "document_key": self.document_key,
            "created": self.created,
            "native_element_ids": list(self.native_element_ids),
        }

    @property
    def digest(self) -> str:
        return hashlib.sha256(_canonical(self.to_dict()).encode()).hexdigest()


@dataclass(frozen=True, slots=True, init=False)
class PromotionOutcome:
    """The outcome's link to an approval and an independent readback, not a
    substitute for them."""

    state: PromotionState
    intent_digest: str
    candidate_digest: str | None = None
    evidence_digest: str | None = None
    approval_ref: str | None = None
    approval_evidence_hash: str | None = None
    readback_evidence_hash: str | None = None
    document_key: str | None = None
    native_element_ids: tuple[int, ...] = ()
    reason: str | None = None

    def __init__(
        self,
        *,
        state: PromotionState,
        intent: ShapeIntent,
        candidate: PromotionCandidate | None = None,
        evidence: PromotionEvidence | None = None,
        reason: str | None = None,
    ) -> None:
        if not isinstance(intent, ShapeIntent):
            raise ShapePromotionError("intent must be ShapeIntent")
        # ``PromotionState`` inherits from ``str``: without an exact type
        # check, the string ``"promoted"`` would pass the membership test
        # below, but then fail to match by identity and wrongly fall into
        # the residual branch. We store only the enum, so one input cannot
        # have two readings and ``to_dict`` cannot break.
        if not isinstance(state, PromotionState):
            raise ShapePromotionError("state must be PromotionState")
        if state not in {PromotionState.PROMOTED, PromotionState.RESIDUAL}:
            raise ShapePromotionError("outcome state must be promoted or residual")
        object.__setattr__(self, "state", state)
        object.__setattr__(self, "intent_digest", intent.digest)
        object.__setattr__(self, "reason", reason)
        object.__setattr__(self, "candidate_digest", None)
        object.__setattr__(self, "evidence_digest", None)
        object.__setattr__(self, "approval_ref", None)
        object.__setattr__(self, "approval_evidence_hash", None)
        object.__setattr__(self, "readback_evidence_hash", None)
        object.__setattr__(self, "document_key", None)
        object.__setattr__(self, "native_element_ids", ())
        if state is PromotionState.PROMOTED:
            if not isinstance(candidate, PromotionCandidate):
                raise ShapePromotionError("promoted outcome needs candidate")
            if candidate.intent.digest != intent.digest:
                raise ShapePromotionError(
                    "candidate must be bound to the same shape intent")
            if not isinstance(evidence, PromotionEvidence):
                raise ShapePromotionError(
                    "promoted outcome needs verified promotion evidence")
            if evidence.candidate_digest != candidate.digest:
                raise ShapePromotionError(
                    "promotion evidence names another candidate")
            object.__setattr__(self, "candidate_digest", candidate.digest)
            object.__setattr__(self, "evidence_digest", evidence.digest)
            object.__setattr__(self, "approval_ref", evidence.approval_ref)
            object.__setattr__(self, "approval_evidence_hash",
                               evidence.approval_evidence_hash)
            object.__setattr__(self, "readback_evidence_hash",
                               evidence.readback_evidence_hash)
            object.__setattr__(self, "document_key", evidence.document_key)
            object.__setattr__(self, "native_element_ids",
                               evidence.native_element_ids)
            if reason is not None:
                raise ShapePromotionError("promoted outcome cannot carry residual reason")
        else:
            object.__setattr__(self, "candidate_digest", None)
            _non_empty(reason or "", "reason")
            if candidate is not None or evidence is not None:
                raise ShapePromotionError(
                    "residual outcome cannot pretend to carry native evidence")

    def to_dict(self) -> dict[str, Any]:
        return {
            "schema": SHAPE_PROMOTION_SCHEMA,
            "state": self.state.value,
            "intent_digest": self.intent_digest,
            "candidate_digest": self.candidate_digest,
            "evidence_digest": self.evidence_digest,
            "approval_ref": self.approval_ref,
            "approval_evidence_hash": self.approval_evidence_hash,
            "readback_evidence_hash": self.readback_evidence_hash,
            "document_key": self.document_key,
            "native_element_ids": list(self.native_element_ids),
            "reason": self.reason,
        }


__all__ = [
    "SHAPE_APPROVAL_SCHEMA", "SHAPE_EVIDENCE_SCHEMA", "SHAPE_INTENT_SCHEMA",
    "SHAPE_PROMOTION_SCHEMA", "SHAPE_READBACK_SCHEMA", "ShapePromotionError",
    "PromotionState", "ShapeIntent", "PromotionCandidate",
    "PromotionEvidence", "PromotionOutcome", "allowed_native_ops",
]
