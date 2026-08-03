"""Reconnect-survival: a durable operation receipt must reach its turn even when
the WS reconnected and the fresh socket is not yet device-identified (device_id="").

Root cause of the Codex-long-turn failure (2026-07-22): while Codex worked for
minutes, the client WS cycled; execute receipts landed on a fresh socket BEFORE it
was device-identified, so the ws/device owner check spuriously rejected them and
orphaned every result → the multi-step task silently did nothing.

Fix (KUKAI_BRIDGE_IDENTITY_ACCEPT, default on): the full OperationIdentity
(turn_id + operation_id + payload_hash) is unique per turn and secret to the owner,
so an identity match is itself proof of ownership — accept regardless of socket.
The identity check itself is NOT relaxed: a foreign/forged receipt is still rejected.
"""
from __future__ import annotations

import asyncio
import uuid

from kukai.api import bridge_protocol as bridge
from kukai.operations.protocol import OperationIdentity, OperationOutcome, OperationPhase
from kukai.operations.store import InMemoryOperationStore, OperationRecord


def _identity(code: str = "return 1;") -> OperationIdentity:
    return OperationIdentity.for_payload(
        turn_id=str(uuid.uuid4()),
        tool_call_id="call-1",
        tool_name="execute_revit_code",
        method="execute",
        params={"code": code, "timeout_ms": 1000},
    )


def _receipt(identity: OperationIdentity) -> dict:
    return {
        **identity.to_mapping(),
        "attempt_id": str(uuid.uuid4()),
        "outcome": OperationOutcome.COMMITTED_VERIFIED.value,
        "result": {"ok": True},
        "changes": {"added": [42], "modified": [], "deleted": []},
    }


def _make_record(identity: OperationIdentity) -> OperationRecord:
    return OperationRecord(
        identity=identity,
        method="execute",
        ws_id="old-ws",
        device_id_hash=bridge._device_hash("device-42"),
        phase=OperationPhase.RUNNING_UNKNOWN,
    )


def test_receipt_accepted_via_identity_when_socket_unidentified(monkeypatch):
    """The exact prod bug: fresh socket, device_id='' → still delivered by identity."""
    async def scenario():
        store = InMemoryOperationStore()
        identity = _identity()
        await store.create(_make_record(identity))
        monkeypatch.setattr(bridge, "_operation_store", lambda: store)

        async def fake_send(_ws, frame):
            pass

        monkeypatch.setattr(bridge, "_send_json", fake_send)
        accepted = await bridge._accept_bridge_response(
            {
                "type": "bridge_response",
                "id": "old-attempt",
                "operation_id": identity.operation_id,
                "receipt": _receipt(identity),
                "receipt_hash": "c" * 64,
                "success": True,
                "result": {"ok": True},
            },
            sender_ws_id="new-ws",   # reconnected socket
            device_id="",            # not yet device-identified (the window that broke it)
            ws=object(),
        )
        assert accepted is True
        rec = await store.get(identity.operation_id)
        assert rec is not None
        assert rec.phase is OperationPhase.RECEIPT_DELIVERED_SERVER

    asyncio.run(scenario())


def test_wrong_identity_still_rejected_under_identity_accept(monkeypatch):
    """Safety: identity-accept relaxes only the SOCKET owner check, never the
    identity check — a receipt whose identity differs from the record is rejected."""
    async def scenario():
        store = InMemoryOperationStore()
        identity = _identity()
        wrong = _identity("return 2;")
        await store.create(_make_record(identity))
        monkeypatch.setattr(bridge, "_operation_store", lambda: store)

        async def fake_send(_ws, frame):
            pass

        monkeypatch.setattr(bridge, "_send_json", fake_send)
        accepted = await bridge._accept_bridge_response(
            {
                "type": "bridge_response",
                "id": "x",
                "operation_id": identity.operation_id,
                "receipt": _receipt(wrong),   # foreign identity
                "success": True,
                "result": {"ok": True},
            },
            sender_ws_id="new-ws",
            device_id="",
            ws=object(),
        )
        assert accepted is False

    asyncio.run(scenario())


def test_kill_switch_restores_strict_owner(monkeypatch):
    """KUKAI_BRIDGE_IDENTITY_ACCEPT=0 → strict owner check again (mismatch rejected)."""
    async def scenario():
        monkeypatch.setenv("KUKAI_BRIDGE_IDENTITY_ACCEPT", "0")
        store = InMemoryOperationStore()
        identity = _identity()
        await store.create(_make_record(identity))
        monkeypatch.setattr(bridge, "_operation_store", lambda: store)

        async def fake_send(_ws, frame):
            pass

        monkeypatch.setattr(bridge, "_send_json", fake_send)
        accepted = await bridge._accept_bridge_response(
            {
                "type": "bridge_response",
                "id": "old-attempt",
                "operation_id": identity.operation_id,
                "receipt": _receipt(identity),
                "success": True,
                "result": {"ok": True},
            },
            sender_ws_id="new-ws",
            device_id="",   # can't match old-ws → strict mode rejects
            ws=object(),
        )
        assert accepted is False

    asyncio.run(scenario())
