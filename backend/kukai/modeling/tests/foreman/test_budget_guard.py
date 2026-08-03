"""Tests for ForemanBudgetGuard — offline retry-spiral tripwire."""
from __future__ import annotations
import httpx
import pytest

from kukai.modeling.bridge.bridge_client import WebSocketBridgeClient
from kukai.modeling.bridge.compile_client import HttpCompileClient
from kukai.modeling.foreman.budget_guard import (
    BudgetCaps, BudgetExceededError, ForemanBudgetGuard,
)
from kukai.modeling.llm.env_config import VertexAIConfig
from kukai.modeling.llm.vertex_client import VertexGeminiClient


class _FakeClient:
    def __init__(self):
        self.calls: list[object] = []


def test_caps_have_sane_defaults():
    caps = BudgetCaps()
    assert caps.max_llm_calls == 100
    assert caps.max_compile_calls == 200
    assert caps.max_execute_calls == 200
    assert caps.max_usd == 5.0


@pytest.fixture
def clients():
    return _FakeClient(), _FakeClient(), _FakeClient()


def test_guard_passes_when_under_caps(clients):
    llm, compile_c, bridge = clients
    caps = BudgetCaps(max_llm_calls=5, max_compile_calls=5, max_execute_calls=5)
    with ForemanBudgetGuard(caps, llm, compile_c, bridge) as guard:
        llm.calls.extend([1, 2, 3])
        compile_c.calls.append(1)
        bridge.calls.append(1)
        guard.check()  # no raise


@pytest.mark.parametrize("attr, kwarg, match", [
    ("llm", "max_llm_calls", "llm"),
    ("compile_c", "max_compile_calls", "compile"),
    ("bridge", "max_execute_calls", "execute"),
])
def test_guard_raises_on_overrun(clients, attr, kwarg, match):
    """Each client kind has its own cap; overrunning surfaces a typed error."""
    llm, compile_c, bridge = clients
    target = {"llm": llm, "compile_c": compile_c, "bridge": bridge}[attr]
    caps = BudgetCaps(**{kwarg: 1})
    with ForemanBudgetGuard(caps, llm, compile_c, bridge) as guard:
        target.calls.extend([1, 2])
        with pytest.raises(BudgetExceededError, match=match):
            guard.check()


# ---------------------------------------------------------------------------
# Wave 6B (Fix B#4) — real clients now expose `.calls` so BudgetGuard works.
#
# Previously mock clients had `.calls` but the three real clients
# (HttpCompileClient, WebSocketBridgeClient, VertexGeminiClient) did not.
# BudgetGuard._count returned 0 in production, caps never tripped, and the
# Wave 3 N1 "wire" was a false-fix. These tests pin the contract.
# ---------------------------------------------------------------------------


@pytest.mark.tier0
def test_http_compile_client_has_calls_list():
    """HttpCompileClient instantiates with an empty .calls list."""
    client = HttpCompileClient(base_url="http://invalid:0")
    assert hasattr(client, "calls"), "HttpCompileClient must expose .calls for BudgetGuard"
    assert client.calls == []


@pytest.mark.tier0
@pytest.mark.asyncio
async def test_http_compile_client_records_call_on_compile():
    """HttpCompileClient.compile appends to .calls on entry, before network I/O."""
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json={"success": True, "errors": []})

    client = HttpCompileClient(
        base_url="http://localhost:52412",
        transport=httpx.MockTransport(handler),
    )
    assert client.calls == []
    await client.compile("// hello", revit_version="2026")
    assert len(client.calls) == 1
    entry = client.calls[0]
    assert entry["method"] == "compile"
    assert "ts" in entry and isinstance(entry["ts"], float)
    assert "revit=2026" in entry["args_summary"]


@pytest.mark.tier0
def test_websocket_bridge_client_has_calls_list():
    """WebSocketBridgeClient instantiates with an empty .calls list."""
    client = WebSocketBridgeClient(base_url="http://invalid:0")
    assert hasattr(client, "calls"), "WebSocketBridgeClient must expose .calls for BudgetGuard"
    assert client.calls == []


@pytest.mark.tier0
@pytest.mark.asyncio
async def test_websocket_bridge_client_records_call_on_execute_code():
    """WebSocketBridgeClient.execute_code appends to .calls on entry."""
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json={
            "success": True, "element_ids": [9000], "duration_ms": 10,
        })

    client = WebSocketBridgeClient(
        base_url="http://localhost:52411",
        transport=httpx.MockTransport(handler),
    )
    assert client.calls == []
    await client.execute_code(session_id="s1", csharp_code="// run", expected_count=1)
    assert len(client.calls) == 1
    entry = client.calls[0]
    assert entry["method"] == "execute_code"
    assert "session=s1" in entry["args_summary"]
    assert "ts" in entry


@pytest.mark.tier0
def test_vertex_gemini_client_has_calls_list():
    """VertexGeminiClient instantiates with an empty .calls list (no network)."""
    fake_config = VertexAIConfig(
        api_key="AQ.fake-test-key", project="fake-project", location="us-central1",
    )
    client = VertexGeminiClient(config=fake_config)
    assert hasattr(client, "calls"), "VertexGeminiClient must expose .calls for BudgetGuard"
    assert client.calls == []


@pytest.mark.tier0
def test_budget_guard_caps_real_http_compile_client():
    """End-to-end: BudgetGuard with cap=2 on a real HttpCompileClient raises
    once its .calls list grows past the cap.

    Tests the integration boundary — we don't need to actually fire HTTP, we
    just need the .calls accounting to be observable by the guard. This proves
    Fix B#4 closes the false-fix from Wave 3 N1.
    """
    real_client = HttpCompileClient(base_url="http://invalid:0")
    other_a, other_b = _FakeClient(), _FakeClient()
    caps = BudgetCaps(max_compile_calls=2)

    with ForemanBudgetGuard(caps, other_a, real_client, other_b) as guard:
        # Simulate 2 compile attempts — should be under cap.
        real_client.calls.append({"method": "compile", "args_summary": "", "ts": 0.0})
        real_client.calls.append({"method": "compile", "args_summary": "", "ts": 0.1})
        guard.check()  # no raise — exactly at cap

        # Third attempt pushes over cap.
        real_client.calls.append({"method": "compile", "args_summary": "", "ts": 0.2})
        with pytest.raises(BudgetExceededError, match="compile"):
            guard.check()


@pytest.mark.tier0
def test_budget_guard_caps_real_websocket_bridge_client():
    """Symmetric to compile-client test: cap=1 on a real WebSocketBridgeClient
    trips after .calls grows past 1.
    """
    real_client = WebSocketBridgeClient(base_url="http://invalid:0")
    other_a, other_b = _FakeClient(), _FakeClient()
    caps = BudgetCaps(max_execute_calls=1)

    with ForemanBudgetGuard(caps, other_a, other_b, real_client) as guard:
        real_client.calls.append({"method": "execute_code", "args_summary": "", "ts": 0.0})
        guard.check()  # at cap
        real_client.calls.append({"method": "execute_code", "args_summary": "", "ts": 0.1})
        with pytest.raises(BudgetExceededError, match="execute"):
            guard.check()
