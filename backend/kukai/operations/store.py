"""Operation-store contracts and production Postgres adapter."""

from __future__ import annotations

import asyncio
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any, Optional, Protocol

from .protocol import OperationIdentity, OperationPhase, transition_allowed


class OperationConflict(RuntimeError):
    """The same operation id was presented with conflicting immutable data."""


@dataclass
class OperationRecord:
    identity: OperationIdentity
    method: str
    ws_id: str = ""
    session_id: str = ""
    tenant_id: str = ""
    device_id_hash: str = ""
    phase: OperationPhase = OperationPhase.CREATED
    attempt_id: str = ""
    outcome: str = ""
    receipt: Optional[dict[str, Any]] = None
    error: Optional[dict[str, Any]] = None
    created_at: str = field(default_factory=lambda: datetime.now(timezone.utc).isoformat())
    updated_at: str = field(default_factory=lambda: datetime.now(timezone.utc).isoformat())

    def as_dict(self) -> dict[str, Any]:
        return {
            **self.identity.to_mapping(),
            "method": self.method,
            "ws_id": self.ws_id,
            "session_id": self.session_id,
            "tenant_id": self.tenant_id,
            "device_id_hash": self.device_id_hash,
            "phase": self.phase.value,
            "attempt_id": self.attempt_id,
            "outcome": self.outcome,
            "receipt": self.receipt,
            "error": self.error,
            "created_at": self.created_at,
            "updated_at": self.updated_at,
        }


class OperationStore(Protocol):
    async def create(self, record: OperationRecord) -> OperationRecord: ...

    async def transition(
        self,
        operation_id: str,
        phase: OperationPhase,
        *,
        attempt_id: str = "",
        outcome: str = "",
        receipt: Optional[dict[str, Any]] = None,
        error: Optional[dict[str, Any]] = None,
    ) -> OperationRecord: ...

    async def get(self, operation_id: str) -> Optional[OperationRecord]: ...


class InMemoryOperationStore:
    """Strict process-local implementation for tests and startup fallback.

    Production injects :class:`DatabaseOperationStore`; this implementation is
    still useful because protocol behavior can be tested without Postgres.
    """

    def __init__(self) -> None:
        self._records: dict[str, OperationRecord] = {}
        self._lock = asyncio.Lock()

    async def create(self, record: OperationRecord) -> OperationRecord:
        async with self._lock:
            old = self._records.get(record.identity.operation_id)
            if old is not None:
                if (
                    old.identity.payload_hash != record.identity.payload_hash
                    or old.identity.action_id != record.identity.action_id
                ):
                    raise OperationConflict("operation id reused with conflicting payload")
                return old
            self._records[record.identity.operation_id] = record
            return record

    async def transition(
        self,
        operation_id: str,
        phase: OperationPhase,
        *,
        attempt_id: str = "",
        outcome: str = "",
        receipt: Optional[dict[str, Any]] = None,
        error: Optional[dict[str, Any]] = None,
    ) -> OperationRecord:
        async with self._lock:
            record = self._records.get(operation_id)
            if record is None:
                raise KeyError(operation_id)
            if not transition_allowed(record.phase, phase):
                raise OperationConflict(
                    f"illegal operation transition {record.phase.value} -> {phase.value}"
                )
            record.phase = phase
            if attempt_id:
                record.attempt_id = attempt_id
            if outcome:
                record.outcome = outcome
            if receipt is not None:
                if record.receipt is not None and record.receipt != receipt:
                    raise OperationConflict("terminal receipt changed on replay")
                record.receipt = receipt
            if error is not None:
                record.error = error
            record.updated_at = datetime.now(timezone.utc).isoformat()
            return record

    async def get(self, operation_id: str) -> Optional[OperationRecord]:
        async with self._lock:
            return self._records.get(operation_id)

    def clear(self) -> None:
        self._records.clear()


class DatabaseOperationStore:
    """Thin adapter over the application's existing async Postgres Database."""

    def __init__(self, database: Any) -> None:
        self._database = database

    async def create(self, record: OperationRecord) -> OperationRecord:
        row = await self._database.create_operation(record.as_dict())
        return _record_from_row(row)

    async def transition(
        self,
        operation_id: str,
        phase: OperationPhase,
        *,
        attempt_id: str = "",
        outcome: str = "",
        receipt: Optional[dict[str, Any]] = None,
        error: Optional[dict[str, Any]] = None,
    ) -> OperationRecord:
        row = await self._database.transition_operation(
            operation_id,
            phase.value,
            attempt_id=attempt_id,
            outcome=outcome,
            receipt=receipt,
            error=error,
        )
        return _record_from_row(row)

    async def get(self, operation_id: str) -> Optional[OperationRecord]:
        row = await self._database.get_operation(operation_id)
        return _record_from_row(row) if row is not None else None


def _record_from_row(row: dict[str, Any]) -> OperationRecord:
    identity = OperationIdentity.from_mapping(row)
    return OperationRecord(
        identity=identity,
        method=str(row.get("method", "")),
        ws_id=str(row.get("ws_id", "")),
        session_id=str(row.get("session_id", "")),
        tenant_id=str(row.get("tenant_id", "")),
        device_id_hash=str(row.get("device_id_hash", "")),
        phase=OperationPhase(str(row.get("phase", OperationPhase.CREATED.value))),
        attempt_id=str(row.get("attempt_id", "")),
        outcome=str(row.get("outcome", "")),
        receipt=row.get("receipt") if isinstance(row.get("receipt"), dict) else None,
        error=row.get("error") if isinstance(row.get("error"), dict) else None,
        created_at=str(row.get("created_at", "")),
        updated_at=str(row.get("updated_at", "")),
    )
