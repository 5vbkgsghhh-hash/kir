"""Behavioral fault tests for operation protocol v2 across bridge transport."""

from __future__ import annotations

import asyncio
import uuid

import pytest

from kukai.api import bridge_protocol as bridge
from kukai.api.ws_registry import _session_keys
from kukai.operations.protocol import (
    OperationIdentity,
    OperationOutcome,
    OperationPhase,
)
from kukai.operations.store import InMemoryOperationStore, OperationRecord


@pytest.fixture(autouse=True)
def _clean_bridge_globals():
    bridge._pending_bridge_requests.clear()
    bridge._pending_bridge_operations.clear()
    bridge._bridge_receipts.clear()
    bridge._bridge_receipt_hashes.clear()
    yield
    bridge._pending_bridge_requests.clear()
    bridge._pending_bridge_operations.clear()
    bridge._bridge_receipts.clear()
    bridge._bridge_receipt_hashes.clear()


def _identity(code: str = "return 1;") -> OperationIdentity:
    return OperationIdentity.for_payload(
        turn_id=str(uuid.uuid4()),
        tool_call_id="call-1",
        tool_name="execute_revit_code",
        method="execute",
        params={"code": code, "timeout_ms": 1000},
    )


def _receipt(identity: OperationIdentity, *, result=None) -> dict:
    return {
        **identity.to_mapping(),
        "attempt_id": str(uuid.uuid4()),
        "outcome": OperationOutcome.COMMITTED_VERIFIED.value,
        "result": result if result is not None else {"ok": True},
        "changes": {"added": [42], "modified": [], "deleted": []},
    }


def _params(identity: OperationIdentity) -> dict:
    return {
        "code": "return 1;",
        "timeout_ms": 1000,
        "_pipeline_prepared": True,
        "_operation": identity.to_mapping(),
    }


def test_write_ahead_receipt_ack_and_deduplicated_replay(monkeypatch):
    async def scenario():
        store = InMemoryOperationStore()
        identity = _identity()
        sent: list[dict] = []
        _session_keys["ws-v2"] = b"k" * 32

        monkeypatch.setattr(bridge, "_operation_store", lambda: store)

        async def fake_send(_ws, frame):
            sent.append(frame)
            if frame.get("type") != "bridge_request":
                return
            # Authoritative row exists before a byte is dispatched.
            before_send = await store.get(identity.operation_id)
            assert before_send is not None
            assert before_send.phase is OperationPhase.PERSISTED_SERVER
            receipt = _receipt(identity)
            bridge._handle_bridge_response(
                {
                    "type": "bridge_response",
                    "id": frame["id"],
                    "operation_id": identity.operation_id,
                    "attempt_id": frame["attempt_id"],
                    "success": True,
                    "result": {"ok": True},
                    "receipt": receipt,
                    "receipt_hash": "a" * 64,
                },
                sender_ws_id="ws-v2",
            )

        monkeypatch.setattr(bridge, "_send_json", fake_send)
        first = await bridge._bridge_callback(object(), "ws-v2", "execute", _params(identity))

        assert first.get("error") is not True
        assert first["operation"]["operation_id"] == identity.operation_id
        assert first["operation"]["verified"] is True
        assert sent[0]["operation_id"] == identity.operation_id
        assert sent[0]["payload_hash"] == identity.payload_hash
        assert sent[-1] == {
            "type": "bridge_ack",
            "protocol_version": 2,
            "operation_id": identity.operation_id,
            "receipt_hash": "a" * 64,
        }
        durable = await store.get(identity.operation_id)
        assert durable is not None
        assert durable.phase is OperationPhase.RECEIPT_DELIVERED_SERVER
        assert durable.receipt is not None

        sends_before_replay = len(sent)
        second = await bridge._bridge_callback(object(), "ws-v2", "execute", _params(identity))
        assert second["operation"]["operation_id"] == identity.operation_id
        assert len(sent) == sends_before_replay  # no second Revit execution

        _session_keys.pop("ws-v2", None)

    asyncio.run(scenario())


def test_timeout_is_nonretryable_running_unknown_and_blocks_redispatch(monkeypatch):
    async def scenario():
        store = InMemoryOperationStore()
        identity = _identity()
        sent: list[dict] = []
        _session_keys["ws-timeout"] = b"k" * 32
        monkeypatch.setattr(bridge, "_operation_store", lambda: store)
        monkeypatch.setattr(bridge, "_effective_bridge_timeout", lambda *_: 0.01)

        async def fake_send(_ws, frame):
            sent.append(frame)

        monkeypatch.setattr(bridge, "_send_json", fake_send)
        result = await bridge._bridge_callback(
            object(), "ws-timeout", "execute", _params(identity)
        )

        assert result["error"] is True
        assert result["state"] == OperationOutcome.RUNNING_UNKNOWN.value
        assert result["err"]["retryable"] is False
        record = await store.get(identity.operation_id)
        assert record is not None and record.phase is OperationPhase.RUNNING_UNKNOWN

        again = await bridge._bridge_callback(
            object(), "ws-timeout", "execute", _params(identity)
        )
        assert again["state"] == OperationOutcome.RUNNING_UNKNOWN.value
        assert len([f for f in sent if f.get("type") == "bridge_request"]) == 1
        _session_keys.pop("ws-timeout", None)

    asyncio.run(scenario())


def test_receiptless_error_does_not_manufacture_rollback_or_commit(monkeypatch):
    async def scenario():
        store = InMemoryOperationStore()
        identity = _identity()
        _session_keys["ws-error"] = b"k" * 32
        monkeypatch.setattr(bridge, "_operation_store", lambda: store)

        async def fake_send(_ws, frame):
            if frame.get("type") == "bridge_request":
                bridge._handle_bridge_response(
                    {
                        "type": "bridge_response",
                        "id": frame["id"],
                        "operation_id": identity.operation_id,
                        "success": False,
                        "error": "client transport failed",
                    },
                    sender_ws_id="ws-error",
                )

        monkeypatch.setattr(bridge, "_send_json", fake_send)
        result = await bridge._bridge_callback(
            object(), "ws-error", "execute", _params(identity)
        )
        assert result["error"] is True
        assert result["operation"]["outcome"] == OperationOutcome.RUNNING_UNKNOWN.value
        record = await store.get(identity.operation_id)
        assert record is not None
        assert record.phase is OperationPhase.RUNNING_UNKNOWN
        assert record.receipt is None
        _session_keys.pop("ws-error", None)

    asyncio.run(scenario())


def test_late_outbox_receipt_reconciles_after_socket_attempt_is_gone(monkeypatch):
    async def scenario():
        store = InMemoryOperationStore()
        identity = _identity()
        device_id = "device-42"
        await store.create(
            OperationRecord(
                identity=identity,
                method="execute",
                ws_id="old-ws",
                device_id_hash=bridge._device_hash(device_id),
                phase=OperationPhase.RUNNING_UNKNOWN,
            )
        )
        monkeypatch.setattr(bridge, "_operation_store", lambda: store)
        sent: list[dict] = []

        async def fake_send(_ws, frame):
            sent.append(frame)

        monkeypatch.setattr(bridge, "_send_json", fake_send)
        receipt = _receipt(identity)
        accepted = await bridge._accept_bridge_response(
            {
                "type": "bridge_response",
                "id": "old-attempt",
                "operation_id": identity.operation_id,
                "receipt": receipt,
                "receipt_hash": "b" * 64,
                "success": True,
                "result": {"ok": True},
            },
            sender_ws_id="new-ws",
            device_id=device_id,
            ws=object(),
        )

        assert accepted is True
        record = await store.get(identity.operation_id)
        assert record is not None
        assert record.phase is OperationPhase.RECEIPT_DELIVERED_SERVER
        assert record.receipt == receipt
        assert sent[-1]["receipt_hash"] == "b" * 64

    asyncio.run(scenario())


def test_mismatched_receipt_identity_cannot_consume_pending_request():
    async def scenario():
        store = InMemoryOperationStore()
        expected = _identity()
        wrong = _identity("return 2;")
        loop = asyncio.get_running_loop()
        future = loop.create_future()
        bridge._pending_bridge_requests["attempt"] = ("owner", future)
        bridge._pending_bridge_operations["attempt"] = (expected, store)

        bridge._handle_bridge_response(
            {
                "id": "attempt",
                "operation_id": expected.operation_id,
                "success": True,
                "result": {"ok": True},
                "receipt": _receipt(wrong),
            },
            sender_ws_id="owner",
        )

        assert "attempt" in bridge._pending_bridge_requests
        assert not future.done()

    asyncio.run(scenario())
