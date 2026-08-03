"""B5 — a bridge_response may only resolve a request OWNED by the same WS
connection that delivered it (cross-session bridge-bleed guard, WAVE0 class).

Behavioral: drive _handle_bridge_response directly with matching/mismatched
sender_ws_id and assert the pending future is resolved only by its true owner.
"""
from __future__ import annotations

import asyncio

import pytest

from kukai.api import chat_ws


@pytest.mark.asyncio
async def test_response_from_wrong_sender_does_not_resolve() -> None:
    loop = asyncio.get_running_loop()
    fut: asyncio.Future = loop.create_future()
    chat_ws._pending_bridge_requests["req-b5"] = ("owner-ws", fut)
    try:
        # a response arriving on a DIFFERENT connection must NOT resolve or consume it
        chat_ws._handle_bridge_response(
            {"id": "req-b5", "success": True, "result": {"x": 1}},
            sender_ws_id="attacker-ws",
        )
        assert not fut.done()                                   # future untouched
        assert "req-b5" in chat_ws._pending_bridge_requests     # still pending for owner

        # the true owner's response resolves it
        chat_ws._handle_bridge_response(
            {"id": "req-b5", "success": True, "result": {"x": 1}},
            sender_ws_id="owner-ws",
        )
        assert fut.done()
        assert fut.result().get("x") == 1
        assert "req-b5" not in chat_ws._pending_bridge_requests
    finally:
        chat_ws._pending_bridge_requests.pop("req-b5", None)


@pytest.mark.asyncio
async def test_no_sender_is_backcompat_and_resolves() -> None:
    loop = asyncio.get_running_loop()
    fut: asyncio.Future = loop.create_future()
    chat_ws._pending_bridge_requests["req-bc"] = ("owner-ws", fut)
    try:
        chat_ws._handle_bridge_response({"id": "req-bc", "success": True, "result": {"ok": True}})
        assert fut.done()
        assert fut.result().get("ok") is True
    finally:
        chat_ws._pending_bridge_requests.pop("req-bc", None)
