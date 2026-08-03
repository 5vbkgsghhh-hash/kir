"""Versioned operation protocol shared by orchestration and bridge transport.

The important distinction is:

* ``action_id`` identifies the user-visible effect;
* ``operation_id`` identifies one concrete, canonical payload for that effect;
* ``attempt_id`` identifies one transport delivery of the operation.

An identical redelivery therefore changes only ``attempt_id``.  A compile
repair changes the payload hash and operation id while retaining the action id.
"""

from __future__ import annotations

import hashlib
import json
import math
import uuid
from dataclasses import dataclass
from enum import Enum
from typing import Any, Mapping

PROTOCOL_VERSION = 2

# Stable public namespace: changing it would change all deterministic ids.
_ACTION_NAMESPACE = uuid.UUID("0e2a73e4-c2bd-4bf3-a40d-d177af442081")
_OPERATION_NAMESPACE = uuid.UUID("ba0a4154-e72d-493a-97be-471e6b360384")


class OperationPhase(str, Enum):
    CREATED = "created"
    PERSISTED_SERVER = "persisted_server"
    SENT = "sent"
    ACCEPTED_CLIENT = "accepted_client"
    QUEUED_REVIT = "queued_revit"
    STARTED = "started"
    COMMITTED = "committed"
    ROLLED_BACK = "rolled_back"
    FAILED_BEFORE_COMMIT = "failed_before_commit"
    COMMITTED_PARTIAL = "committed_partial"
    VERIFIED = "verified"
    UNVERIFIED = "unverified"
    RECEIPT_PERSISTED_CLIENT = "receipt_persisted_client"
    RECEIPT_DELIVERED_SERVER = "receipt_delivered_server"
    ACKNOWLEDGED = "acknowledged"
    CANCELLED_BEFORE_START = "cancelled_before_start"
    RUNNING_UNKNOWN = "running_unknown"


class OperationOutcome(str, Enum):
    REJECTED_BEFORE_EXECUTION = "RejectedBeforeExecution"
    CANCELLED_BEFORE_START = "CancelledBeforeStart"
    FAILED_BEFORE_COMMIT = "FailedBeforeCommit"
    ROLLED_BACK = "RolledBack"
    COMMITTED_VERIFIED = "CommittedVerified"
    COMMITTED_UNVERIFIED = "CommittedUnverified"
    COMMITTED_PARTIAL = "CommittedPartial"
    RUNNING_UNKNOWN = "RunningUnknown"


# Ranks are lifecycle progress, not a license to skip validation.  Several
# terminal branches intentionally share a rank.
PHASE_RANK: dict[OperationPhase, int] = {
    OperationPhase.CREATED: 10,
    OperationPhase.PERSISTED_SERVER: 20,
    OperationPhase.SENT: 30,
    OperationPhase.ACCEPTED_CLIENT: 40,
    OperationPhase.QUEUED_REVIT: 50,
    OperationPhase.STARTED: 60,
    OperationPhase.RUNNING_UNKNOWN: 65,
    OperationPhase.COMMITTED: 70,
    OperationPhase.ROLLED_BACK: 70,
    OperationPhase.FAILED_BEFORE_COMMIT: 70,
    OperationPhase.COMMITTED_PARTIAL: 70,
    OperationPhase.CANCELLED_BEFORE_START: 70,
    OperationPhase.VERIFIED: 80,
    OperationPhase.UNVERIFIED: 80,
    OperationPhase.RECEIPT_PERSISTED_CLIENT: 90,
    OperationPhase.RECEIPT_DELIVERED_SERVER: 100,
    OperationPhase.ACKNOWLEDGED: 110,
}

_BRANCH_TERMINALS = frozenset(
    {
        OperationPhase.ROLLED_BACK,
        OperationPhase.FAILED_BEFORE_COMMIT,
        OperationPhase.CANCELLED_BEFORE_START,
    }
)

_FINAL_TERMINALS = frozenset(
    {
        OperationPhase.ACKNOWLEDGED,
        *_BRANCH_TERMINALS,
    }
)


def is_terminal_phase(phase: OperationPhase | str) -> bool:
    """Whether no later execution can occur for this operation.

    ``COMMITTED`` is not final because verification/receipt delivery still
    follows, while failed/rolled-back/cancelled operations cannot execute.
    """

    try:
        return OperationPhase(phase) in _FINAL_TERMINALS
    except ValueError:
        return False


def transition_allowed(current: OperationPhase | str, new: OperationPhase | str) -> bool:
    """Validate monotonic lifecycle transitions and terminal immutability."""

    try:
        old = OperationPhase(current)
        nxt = OperationPhase(new)
    except ValueError:
        return False
    if old == nxt:
        return True  # idempotent replay
    if old is OperationPhase.ACKNOWLEDGED:
        return False

    # Execution has ended, but its durable receipt still has to cross the
    # client/server boundary and be acknowledged before lifecycle completion.
    if old in _BRANCH_TERMINALS:
        return nxt in {
            OperationPhase.RECEIPT_PERSISTED_CLIENT,
            OperationPhase.RECEIPT_DELIVERED_SERVER,
            OperationPhase.ACKNOWLEDGED,
        }

    # RunningUnknown is an observation while work may continue.  A late
    # receipt is explicitly allowed to resolve it to any execution terminal.
    if old is OperationPhase.RUNNING_UNKNOWN:
        return nxt in {
            OperationPhase.COMMITTED,
            OperationPhase.COMMITTED_PARTIAL,
            OperationPhase.ROLLED_BACK,
            OperationPhase.FAILED_BEFORE_COMMIT,
            OperationPhase.RECEIPT_PERSISTED_CLIENT,
            OperationPhase.RECEIPT_DELIVERED_SERVER,
        }

    # "Cancelled before start" is a statement about the past: it may only be
    # reached from phases that precede STARTED.  Without this rule the generic
    # rank fallback would accept STARTED(60) -> CANCELLED_BEFORE_START(70) and
    # let a buggy or malicious protocol-v2 client rewrite a started execution
    # into "never ran".
    if nxt is OperationPhase.CANCELLED_BEFORE_START:
        return PHASE_RANK[old] <= PHASE_RANK[OperationPhase.QUEUED_REVIT]

    # Execution terminal branches cannot be changed into each other.  They may
    # only advance through receipt delivery/ack where applicable.
    if old in {
        OperationPhase.COMMITTED,
        OperationPhase.COMMITTED_PARTIAL,
    }:
        return nxt in {
            OperationPhase.VERIFIED,
            OperationPhase.UNVERIFIED,
            OperationPhase.RECEIPT_PERSISTED_CLIENT,
            OperationPhase.RECEIPT_DELIVERED_SERVER,
            OperationPhase.ACKNOWLEDGED,
        }

    return PHASE_RANK[nxt] >= PHASE_RANK[old]


def _canonical(value: Any) -> Any:
    """Convert a payload to deterministic, JSON-safe data.

    Internal transport metadata is deliberately excluded from hashes.  Booleans
    remain distinct from integers; NaN/Infinity are rejected because they have
    no portable JSON representation across Python/JavaScript/C#.
    """

    if value is None or isinstance(value, (str, bool, int)):
        return value
    if isinstance(value, float):
        if not math.isfinite(value):
            raise ValueError("operation payload contains a non-finite number")
        # JSON's shortest round-trippable representation is deterministic on
        # supported Python versions; -0.0 is normalized to 0.0 cross-language.
        return 0.0 if value == 0 else value
    if isinstance(value, Mapping):
        return {
            str(key): _canonical(item)
            for key, item in sorted(value.items(), key=lambda kv: str(kv[0]))
            if str(key) not in {"_operation", "attempt", "_pipeline_prepared"}
        }
    if isinstance(value, (list, tuple)):
        return [_canonical(item) for item in value]
    # Payloads should already be JSON data.  A stable string fallback keeps the
    # identity layer defensive without silently using object memory addresses.
    return str(value)


def canonical_payload_hash(method: str, params: Mapping[str, Any]) -> str:
    body = {
        "method": str(method or ""),
        "params": _canonical(params or {}),
    }
    encoded = json.dumps(
        body,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
        allow_nan=False,
    ).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def derive_action_id(turn_id: str, tool_call_id: str, tool_name: str) -> str:
    seed = f"{turn_id or 'turn-unknown'}\n{tool_call_id or 'call-unknown'}\n{tool_name or ''}"
    return str(uuid.uuid5(_ACTION_NAMESPACE, seed))


def derive_operation_id(action_id: str, method: str, payload_hash: str) -> str:
    seed = f"{action_id}\n{method}\n{payload_hash}"
    return str(uuid.uuid5(_OPERATION_NAMESPACE, seed))


def _bounded_id(value: Any, field: str) -> str:
    text = str(value or "").strip()
    if not text or len(text) > 128:
        raise ValueError(f"invalid {field}")
    return text


@dataclass(frozen=True)
class OperationIdentity:
    turn_id: str
    action_id: str
    operation_id: str
    payload_hash: str
    protocol_version: int = PROTOCOL_VERSION

    @classmethod
    def for_payload(
        cls,
        *,
        turn_id: str,
        tool_call_id: str,
        tool_name: str,
        method: str,
        params: Mapping[str, Any],
    ) -> "OperationIdentity":
        payload_hash = canonical_payload_hash(method, params)
        action_id = derive_action_id(turn_id, tool_call_id, tool_name)
        return cls(
            turn_id=_bounded_id(turn_id or uuid.uuid4(), "turn_id"),
            action_id=action_id,
            operation_id=derive_operation_id(action_id, method, payload_hash),
            payload_hash=payload_hash,
        )

    @classmethod
    def from_mapping(cls, data: Mapping[str, Any]) -> "OperationIdentity":
        version = int(data.get("protocol_version", PROTOCOL_VERSION))
        if version != PROTOCOL_VERSION:
            raise ValueError(f"unsupported operation protocol version: {version}")
        payload_hash = str(data.get("payload_hash", ""))
        if len(payload_hash) != 64 or any(c not in "0123456789abcdef" for c in payload_hash.lower()):
            raise ValueError("invalid payload_hash")
        return cls(
            turn_id=_bounded_id(data.get("turn_id"), "turn_id"),
            action_id=_bounded_id(data.get("action_id"), "action_id"),
            operation_id=_bounded_id(data.get("operation_id"), "operation_id"),
            payload_hash=payload_hash.lower(),
            protocol_version=version,
        )

    def to_mapping(self) -> dict[str, Any]:
        return {
            "protocol_version": self.protocol_version,
            "turn_id": self.turn_id,
            "action_id": self.action_id,
            "operation_id": self.operation_id,
            "payload_hash": self.payload_hash,
        }
