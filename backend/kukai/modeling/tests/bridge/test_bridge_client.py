"""Tests for WebSocketBridgeClient.

Uses an in-process FastAPI app to simulate the spike endpoint, so we don't
need a real Revit. Real bridge integration is gated by Phase 0 Spike data.
"""
from __future__ import annotations
import json as _json
import pytest
import httpx

from kukai.modeling.bridge.bridge_client import WebSocketBridgeClient


@pytest.fixture
def mock_http_transport():
    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path == "/api/spike/execute":
            raw = request.read().decode() if request.method == "POST" else ""
            body = _json.loads(raw) if raw else {}
            code = body.get("code", "")
            if "throw new" in code:
                return httpx.Response(200, json={
                    "success": False,
                    "error": "Revit threw InvalidOperationException",
                    "element_ids": [],
                    "duration_ms": 35,
                })
            # Simulate creating 1 element by default
            count = body.get("expected_count", 1)
            return httpx.Response(200, json={
                "success": True,
                "element_ids": list(range(9000, 9000 + count)),
                "duration_ms": 120,
            })
        if request.url.path == "/api/spike/sessions":
            return httpx.Response(200, json={"sessions": ["dev_session_1"]})
        return httpx.Response(404)
    return httpx.MockTransport(handler)


@pytest.mark.asyncio
async def test_execute_code_success(mock_http_transport):
    client = WebSocketBridgeClient(
        base_url="http://localhost:52411",
        transport=mock_http_transport,
    )
    result = await client.execute_code(
        session_id="dev_session_1",
        csharp_code="// ok",
        expected_count=2,
    )
    assert result["success"] is True
    assert result["element_ids"] == [9000, 9001]


@pytest.mark.asyncio
async def test_execute_code_failure(mock_http_transport):
    client = WebSocketBridgeClient(
        base_url="http://localhost:52411",
        transport=mock_http_transport,
    )
    result = await client.execute_code(
        session_id="dev_session_1",
        csharp_code="throw new InvalidOperationException();",
        expected_count=1,
    )
    assert result["success"] is False
    assert "InvalidOperation" in result["error"]
    assert result["element_ids"] == []


@pytest.mark.asyncio
async def test_list_sessions(mock_http_transport):
    client = WebSocketBridgeClient(
        base_url="http://localhost:52411",
        transport=mock_http_transport,
    )
    sessions = await client.list_sessions()
    assert sessions == ["dev_session_1"]


# ---- Wave 6C — Fix A+B#3: execute_code serialization ----

@pytest.mark.tier0
@pytest.mark.asyncio
async def test_concurrent_execute_code_serializes_via_lock():
    """Three concurrent execute_code calls on the same client must not
    interleave. We monkey-patch the inner network call with an async sleep
    that records (entry_ts, exit_ts) and assert each call's entry is
    >= the previous call's exit.

    Revit's API is single-threaded; without the per-client asyncio.Lock
    concurrent dispatchers would interleave WebSocket frames into Revit
    and corrupt the transaction model (Wave 6C — Fix A+B#3).
    """
    import asyncio
    import time as time_mod

    events: list[tuple[str, str, float]] = []  # (tag, kind, ts)

    async def fake_post(self, url, json=None):
        """Stand-in for the inner async-client POST. Sleeps a measurable
        interval so overlap would be observable if the lock were absent."""
        events.append((json["session_id"], "enter", time_mod.monotonic()))
        await asyncio.sleep(0.05)
        events.append((json["session_id"], "exit", time_mod.monotonic()))

        class _R:
            status_code = 200

            def raise_for_status(self):
                return None

            def json(self):
                return {"success": True, "element_ids": [9000], "duration_ms": 50}
        return _R()

    class _FakeAsyncClient:
        def __init__(self, **kwargs):
            pass

        async def __aenter__(self):
            return self

        async def __aexit__(self, *a):
            return False

        async def post(self, url, json=None):
            return await fake_post(self, url, json=json)

    client = WebSocketBridgeClient(base_url="http://localhost:52411")
    # Monkey-patch the httpx.AsyncClient factory to return our fake.
    client._client = lambda: _FakeAsyncClient()

    tasks = [
        asyncio.create_task(client.execute_code(
            session_id=f"sess_{i}", csharp_code=f"// {i}", expected_count=1))
        for i in range(3)
    ]
    results = await asyncio.gather(*tasks)
    assert all(r["success"] for r in results)

    # Partition into per-call (enter, exit) pairs in event-order
    pairs: list[tuple[str, float, float]] = []
    pending: dict[str, float] = {}
    for tag, kind, ts in events:
        if kind == "enter":
            pending[tag] = ts
        else:  # exit
            assert tag in pending, f"exit before enter for {tag}"
            pairs.append((tag, pending.pop(tag), ts))

    assert len(pairs) == 3, f"expected 3 (enter,exit) pairs, got {len(pairs)}"
    # Sort by entry time and assert serial ordering: each enter >= prev exit
    pairs.sort(key=lambda p: p[1])
    for i in range(1, len(pairs)):
        prev_exit = pairs[i - 1][2]
        cur_enter = pairs[i][1]
        assert cur_enter >= prev_exit, (
            f"calls overlap: {pairs[i-1]} then {pairs[i]} "
            f"(prev_exit={prev_exit:.4f} > cur_enter={cur_enter:.4f})"
        )

    # All three calls must also be recorded in client.calls (Wave 6B contract).
    assert len(client.calls) == 3


@pytest.mark.tier0
@pytest.mark.asyncio
async def test_list_sessions_is_not_blocked_by_execute_lock(mock_http_transport):
    """list_sessions is read-only — it should NOT acquire the execute_code
    lock. Verifying this prevents an accidental future change that makes
    session listing also block on long-running executions."""
    client = WebSocketBridgeClient(
        base_url="http://localhost:52411",
        transport=mock_http_transport,
    )
    # Take the lock manually and confirm list_sessions still runs.
    lock = client._get_exec_lock()
    async with lock:
        sessions = await client.list_sessions()
    assert sessions == ["dev_session_1"]
