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
    DISPATCH_CLAIMED = "dispatch_claimed"
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
    OperationPhase.DISPATCH_CLAIMED: 25,
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


#: 🔴 AN EXPLICIT TRANSITION GRAPH (2026-08-29, audit finding F-330). Before
#: it, everything not caught by the branches below was decided by comparing
#: RANKS, and that is why CREATED -> VERIFIED, CREATED -> ACKNOWLEDGED, and
#: SENT -> ACKNOWLEDGED were ALLOWED: an operation that was NEVER SENT (an
#: empty `attempt_id`, no `claim_dispatch`, no receipt) could be declared
#: terminally accepted with the outcome CommittedVerified. `is_terminal_phase`
#: is true for it, meaning it can no longer be retried: the building's side
#: effect either happened and was not recorded, or did not happen and never
#: will, and there is nothing left in the operations journal to tell the two apart.
#:
#: The same rank also allowed DOWNGRADING A PROVEN FACT: VERIFIED and
#: UNVERIFIED both have rank 80, meaning a verified state could be rewritten
#: into an unverified one and back. These are DIFFERENT FACTS, not
#: neighboring steps.
#:
#: The comment above `PHASE_RANK` had been saying all along "ranks are not a
#: license to skip validation." The graph makes this phrase a PROPERTY, not a
#: wish: it answers every pair at once and by construction, whereas the list
#: of exception branches grew as findings accumulated and never caught up.
#:
#: `PHASE_RANK` IS NOT REMOVED: it is read externally and remains an honest
#: answer to ITS OWN question — "is this phase further along in order." What
#: was being asked of it was different: "is this transition legal."
#: CREATED(10) -> ACKNOWLEDGED(110) is further along in order and illegal.
#:
#: BLAST-RADIUS MEASUREMENT (performed by enumerating all pairs, see the
#: commit message): the fix only NARROWS things, zero new permissions. All
#: live transitions of the owner (`kukai/api/bridge_protocol.py`) were
#: checked by name and preserved — in particular SENT ->
#: RECEIPT_DELIVERED_SERVER, which the owner does BYPASSING
#: ACCEPTED_CLIENT/QUEUED_REVIT/STARTED: the client does not report those to
#: the server, everything travels in one receipt. A graph written as "how it
#: should be," rather than "how it is," would have broken prod within the first hour.
_ALLOWED_TRANSITIONS: dict[OperationPhase, frozenset[OperationPhase]] = {
    # Before sending, NOTHING happened that could be witnessed.
    OperationPhase.CREATED: frozenset({
        OperationPhase.PERSISTED_SERVER,
        OperationPhase.DISPATCH_CLAIMED,
        OperationPhase.CANCELLED_BEFORE_START,
    }),
    OperationPhase.PERSISTED_SERVER: frozenset({
        OperationPhase.DISPATCH_CLAIMED,
        OperationPhase.CANCELLED_BEFORE_START,
    }),
    # A send request has been made: the bytes COULD have gone out on the
    # wire, so "unknown" and a receipt arriving are legitimate, but
    # "committed" is not yet. "The receipt arrived" is a fact about the
    # SERVER; "committed" is a fact about REVIT, and only the receipt brings that.
    OperationPhase.DISPATCH_CLAIMED: frozenset({
        OperationPhase.SENT,
        OperationPhase.RUNNING_UNKNOWN,
        OperationPhase.FAILED_BEFORE_COMMIT,
        OperationPhase.CANCELLED_BEFORE_START,
        OperationPhase.RECEIPT_PERSISTED_CLIENT,
        OperationPhase.RECEIPT_DELIVERED_SERVER,
    }),
    OperationPhase.SENT: frozenset({
        OperationPhase.ACCEPTED_CLIENT, OperationPhase.QUEUED_REVIT,
        OperationPhase.STARTED, OperationPhase.RUNNING_UNKNOWN,
        OperationPhase.COMMITTED, OperationPhase.COMMITTED_PARTIAL,
        OperationPhase.ROLLED_BACK, OperationPhase.FAILED_BEFORE_COMMIT,
        OperationPhase.CANCELLED_BEFORE_START,
        OperationPhase.RECEIPT_PERSISTED_CLIENT,
        OperationPhase.RECEIPT_DELIVERED_SERVER,
    }),
    OperationPhase.ACCEPTED_CLIENT: frozenset({
        OperationPhase.QUEUED_REVIT, OperationPhase.STARTED,
        OperationPhase.RUNNING_UNKNOWN,
        OperationPhase.COMMITTED, OperationPhase.COMMITTED_PARTIAL,
        OperationPhase.ROLLED_BACK, OperationPhase.FAILED_BEFORE_COMMIT,
        OperationPhase.CANCELLED_BEFORE_START,
        OperationPhase.RECEIPT_PERSISTED_CLIENT,
        OperationPhase.RECEIPT_DELIVERED_SERVER,
    }),
    OperationPhase.QUEUED_REVIT: frozenset({
        OperationPhase.STARTED, OperationPhase.RUNNING_UNKNOWN,
        OperationPhase.COMMITTED, OperationPhase.COMMITTED_PARTIAL,
        OperationPhase.ROLLED_BACK, OperationPhase.FAILED_BEFORE_COMMIT,
        OperationPhase.CANCELLED_BEFORE_START,
        OperationPhase.RECEIPT_PERSISTED_CLIENT,
        OperationPhase.RECEIPT_DELIVERED_SERVER,
    }),
    # Execution has started: canceling "before it started" is no longer
    # possible. This was the ONLY rule that was closed, and it is preserved verbatim.
    OperationPhase.STARTED: frozenset({
        OperationPhase.RUNNING_UNKNOWN,
        OperationPhase.COMMITTED, OperationPhase.COMMITTED_PARTIAL,
        OperationPhase.ROLLED_BACK, OperationPhase.FAILED_BEFORE_COMMIT,
        OperationPhase.RECEIPT_PERSISTED_CLIENT,
        OperationPhase.RECEIPT_DELIVERED_SERVER,
    }),
    # The existing rule for a late receipt — carried over verbatim.
    OperationPhase.RUNNING_UNKNOWN: frozenset({
        OperationPhase.COMMITTED, OperationPhase.COMMITTED_PARTIAL,
        OperationPhase.ROLLED_BACK, OperationPhase.FAILED_BEFORE_COMMIT,
        OperationPhase.RECEIPT_PERSISTED_CLIENT,
        OperationPhase.RECEIPT_DELIVERED_SERVER,
    }),
    OperationPhase.COMMITTED: frozenset({
        OperationPhase.VERIFIED, OperationPhase.UNVERIFIED,
        OperationPhase.RECEIPT_PERSISTED_CLIENT,
        OperationPhase.RECEIPT_DELIVERED_SERVER, OperationPhase.ACKNOWLEDGED,
    }),
    OperationPhase.COMMITTED_PARTIAL: frozenset({
        OperationPhase.VERIFIED, OperationPhase.UNVERIFIED,
        OperationPhase.RECEIPT_PERSISTED_CLIENT,
        OperationPhase.RECEIPT_DELIVERED_SERVER, OperationPhase.ACKNOWLEDGED,
    }),
    # 🔴 "Verified" and "unverified" are DIFFERENT FACTS: rank 80 for both
    # allowed rewriting one into the other in BOTH directions.
    OperationPhase.VERIFIED: frozenset({
        OperationPhase.RECEIPT_PERSISTED_CLIENT,
        OperationPhase.RECEIPT_DELIVERED_SERVER, OperationPhase.ACKNOWLEDGED,
    }),
    OperationPhase.UNVERIFIED: frozenset({
        OperationPhase.RECEIPT_PERSISTED_CLIENT,
        OperationPhase.RECEIPT_DELIVERED_SERVER, OperationPhase.ACKNOWLEDGED,
    }),
    OperationPhase.RECEIPT_PERSISTED_CLIENT: frozenset({
        OperationPhase.RECEIPT_DELIVERED_SERVER, OperationPhase.ACKNOWLEDGED,
    }),
    OperationPhase.RECEIPT_DELIVERED_SERVER: frozenset({
        OperationPhase.ACKNOWLEDGED,
    }),
    # Branch terminals — the existing rule, carried over verbatim.
    OperationPhase.ROLLED_BACK: frozenset({
        OperationPhase.RECEIPT_PERSISTED_CLIENT,
        OperationPhase.RECEIPT_DELIVERED_SERVER, OperationPhase.ACKNOWLEDGED,
    }),
    OperationPhase.FAILED_BEFORE_COMMIT: frozenset({
        OperationPhase.RECEIPT_PERSISTED_CLIENT,
        OperationPhase.RECEIPT_DELIVERED_SERVER, OperationPhase.ACKNOWLEDGED,
    }),
    OperationPhase.CANCELLED_BEFORE_START: frozenset({
        OperationPhase.RECEIPT_PERSISTED_CLIENT,
        OperationPhase.RECEIPT_DELIVERED_SERVER, OperationPhase.ACKNOWLEDGED,
    }),
    OperationPhase.ACKNOWLEDGED: frozenset(),
}

#: 🔴 THE GRAPH'S COMPLETENESS IS A PROPERTY, NOT A PROMISE. A new phase
#: without its own row would give a `KeyError` at runtime FOR THE USER,
#: rather than a red for the author. The list is CLOSED by construction, not by memory.
_MISSING_IN_GRAPH = set(OperationPhase) - set(_ALLOWED_TRANSITIONS)
if _MISSING_IN_GRAPH:
    raise RuntimeError(
        "фаза заведена, а её строка в графе переходов — нет: "
        + ", ".join(sorted(p.value for p in _MISSING_IN_GRAPH)))


def transition_allowed(current: OperationPhase | str, new: OperationPhase | str) -> bool:
    """Validate lifecycle transitions against the explicit graph.

    🔴 A GRAPH, NOT A RANK (F-330). The rank answered the question "is this
    phase further along in order," while what was being asked of it was "is
    this transition legal." These are DIFFERENT questions:
    `CREATED(10) -> ACKNOWLEDGED(110)` is further along in order and illegal.
    Rules that used to stand as separate branches (branch terminals, a late
    receipt under RUNNING_UNKNOWN, the ban on "canceled before it started"
    after STARTED, the immutability of terminals) are carried into the graph
    VERBATIM — it does not weaken them, it merely fills in the definition for
    the remaining pairs.
    """

    try:
        old = OperationPhase(current)
        nxt = OperationPhase(new)
    except ValueError:
        return False
    if old == nxt:
        return True  # idempotent replay
    return nxt in _ALLOWED_TRANSITIONS[old]


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
            if str(key) not in {
                "_operation",
                "attempt",
                "_pipeline_prepared",
                # Private process-local capability: its adjacent
                # ``_kir_execution_artifact_binding_digest`` remains in the
                # payload and is the portable content address.  Hashing the
                # Python object's repr would make operation ids depend on an
                # implementation detail rather than canonical JSON.
                "_kir_execution_artifact_binding",
            }
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


def _bounded_id(value: Any, field: str) -> str:
    text = str(value or "").strip()
    if not text or len(text) > 128:
        raise ValueError(f"invalid {field}")
    return text


#: 🔴 AN UNNAMED TURN IS A REFUSAL, NOT A SUBSTITUTION (2026-09-04, finding
#: RT-29). The literal `turn_id or 'turn-unknown'` used to stand here, while
#: `for_payload` nearby put a FRESH uuid4 into the `turn_id` field. The two
#: states were mixed silently, and the measurement showed it: two calls with
#: `turn_id=""` give DIFFERENT `turn_id` values in the field and IDENTICAL
#: `action_id`/`operation_id`. That is, two turns declared different are
#: indistinguishable by the operation's identity — and the operation's
#: identity is exactly what the bridge uses to decide "is this a new action
#: or a repeat of an old one."
#:
#: WHY A REFUSAL, NOT "let the uuid take part in the output." The second path
#: fixes the merging of two turns at the cost of SPLITTING one: a genuine
#: RE-DELIVERY of the same unnamed turn would get fresh `action_id` and
#: `operation_id`, and the building would get built TWICE. This is exactly
#: what the owner's comment in `kukai/api/bridge_protocol.py` forbids: "never
#: acquire a fresh random operation id and execute twice." Only the CALLER,
#: who has a retry policy, can tell "a new turn" apart from "a repeat"; there
#: is no such knowledge here by construction.
#:
#: THE COST TO LIVE CALLERS IS ZERO, AND THIS IS MEASURED BY NAME:
#: `acceptance_runtime` gives `binding.run_id`; `bridge_protocol` gives
#: `artifact_binding.run_id` or `ledger.turn_id if ledger is not None else
#: str(uuid.uuid4())` — that is, the owner ALREADY generates a uuid on its
#: own side and passes it in NAMED; `admin_kir` gives `uuid.uuid4().hex`. Not
#: one live path relied on the substitution — it only worked on the emptiness
#: that no one was actually sending.
#:
#: `'call-unknown'` next to it is left DELIBERATELY, and this is not the same
#: mistake: a turn is an EXTERNAL frame (two different turns are two
#: different actions by definition), while two calls of ONE turn with the
#: same tool and the same payload can legitimately be counted as one action.
#: There is no separate measurement for an empty `tool_call_id`, and changing
#: it blindly would mean moving the operation's identity without a number.
def derive_action_id(turn_id: str, tool_call_id: str, tool_name: str) -> str:
    turn = _bounded_id(turn_id, "turn_id")
    seed = f"{turn}\n{tool_call_id or 'call-unknown'}\n{tool_name or ''}"
    return str(uuid.uuid5(_ACTION_NAMESPACE, seed))


def derive_operation_id(action_id: str, method: str, payload_hash: str) -> str:
    seed = f"{action_id}\n{method}\n{payload_hash}"
    return str(uuid.uuid5(_OPERATION_NAMESPACE, seed))


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
        # ONE TURN VALUE FOR BOTH PATHS. Before, the field and the derivation
        # took the turn from DIFFERENT sources: the field from `turn_id or
        # uuid.uuid4()`, the derivation from `turn_id or 'turn-unknown'`. Now
        # the turn is named once, and what is recorded in the field is
        # exactly what `action_id` is derived from.
        turn = _bounded_id(turn_id, "turn_id")
        payload_hash = canonical_payload_hash(method, params)
        action_id = derive_action_id(turn, tool_call_id, tool_name)
        return cls(
            turn_id=turn,
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
