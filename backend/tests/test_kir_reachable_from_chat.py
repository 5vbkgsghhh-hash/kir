"""KIR's gate must be able to see the device of a CHAT turn.

`revit_ir_enabled()` is `KUKAI_KIR_TOOL=stage2 AND turn_context._active_device_id
== ADMIN_DEVICE`. That ContextVar was written only by the admin_kir HTTP
endpoints, so in chat it was always None and the tool was never offered — the
flag was on, the compiler worked, admin-driven writes landed, and the model
still answered "в текущем сеансе недоступен revit_ir" (four turns in a row,
2026-07-27). These pin the wiring, not the gate policy.
"""
from __future__ import annotations

import inspect

import pytest

from kukai.api import chat_ws
from kukai.ir import serving
from kukai.llm import turn_context


@pytest.fixture(autouse=True)
def _clean_ctx():
    token = turn_context._active_device_id.set(None)
    yield
    turn_context._active_device_id.reset(token)


def test_run_turn_publishes_the_device_for_the_kir_gate():
    """Source-shape guard: the bind must live in run_turn, before tools resolve."""
    src = inspect.getsource(chat_ws.run_turn)
    assert "_active_device_id.set(ctx.device_id)" in src, (
        "chat turns must publish their device or KIR is invisible in chat")
    head = src[: src.index("collected_text")] if "collected_text" in src else src
    assert "_active_device_id.set(ctx.device_id)" in head, (
        "the bind must happen before the stream starts, not after")


def test_gate_opens_for_the_admin_device(monkeypatch):
    monkeypatch.setenv("KUKAI_KIR_TOOL", "stage2")
    turn_context._active_device_id.set(serving.ADMIN_DEVICE)
    assert serving.revit_ir_enabled() is True


def test_gate_stays_shut_for_everyone_else(monkeypatch):
    monkeypatch.setenv("KUKAI_KIR_TOOL", "stage2")
    turn_context._active_device_id.set("some-other-device")
    assert serving.revit_ir_enabled() is False


def test_gate_stays_shut_without_the_flag(monkeypatch):
    monkeypatch.setenv("KUKAI_KIR_TOOL", "off")
    turn_context._active_device_id.set(serving.ADMIN_DEVICE)
    assert serving.revit_ir_enabled() is False


def test_gate_stays_shut_when_no_device_is_bound(monkeypatch):
    """The state that hid the tool for weeks — keep it failing closed."""
    monkeypatch.setenv("KUKAI_KIR_TOOL", "stage2")
    turn_context._active_device_id.set(None)
    assert serving.revit_ir_enabled() is False


def test_the_cached_panel_gains_the_tool_only_for_the_admin_turn(monkeypatch):
    """`self._tools` is built once at import, with no turn and no device — so a
    device-gated tool can only ever be added per request. Gate shut ⇒ the SAME
    list object comes back (cached-identity contract + byte-identical turns)."""
    from kukai.llm.client import _inject_per_turn_tools

    monkeypatch.setenv("KUKAI_KIR_TOOL", "stage2")
    base = [{"type": "function", "function": {"name": "query_model"}}]

    turn_context._active_device_id.set(None)
    assert _inject_per_turn_tools(base) is base

    turn_context._active_device_id.set("someone-else")
    assert _inject_per_turn_tools(base) is base

    turn_context._active_device_id.set(serving.ADMIN_DEVICE)
    out = _inject_per_turn_tools(base)
    assert [t["function"]["name"] for t in out] == ["query_model", "revit_ir"]
    assert [t["function"]["name"] for t in base] == ["query_model"], "shared cache mutated"


def test_resolve_tools_offers_revit_ir_on_an_admin_turn(monkeypatch):
    """End to end through the real resolver — the path the turn actually uses."""
    monkeypatch.setenv("KUKAI_KIR_TOOL", "stage2")
    from kukai.llm.client import LLMClient

    client = LLMClient.__new__(LLMClient)
    client._tools = [{"type": "function", "function": {"name": "query_model"}}]
    client._module_registry = None

    turn_context._active_device_id.set(None)
    assert "revit_ir" not in [t["function"]["name"] for t in client._resolve_tools(None)]

    turn_context._active_device_id.set(serving.ADMIN_DEVICE)
    assert "revit_ir" in [t["function"]["name"] for t in client._resolve_tools(None)]


def test_the_tool_actually_lands_in_the_list(monkeypatch):
    monkeypatch.setenv("KUKAI_KIR_TOOL", "stage2")
    turn_context._active_device_id.set(serving.ADMIN_DEVICE)
    tools: list = []
    serving.inject_revit_ir_schema(tools)
    assert [t["function"]["name"] for t in tools] == ["revit_ir"]
    desc = tools[0]["function"]["description"]
    # The description is co-authored; assert the CONTENT the model cannot infer,
    # not a heading someone may reword.
    assert "это ТИП, а не параметр" in desc, "the type-vs-parameter idiom must ship"
    # Assert the NUMBER agrees with the compiler, never a literal: telling the
    # model 300 when the serving cap is 20 cost a refused program and a rewrite
    # (KIR-L001, expected <=20, got 24 — 2026-07-27).
    import re

    from kukai.ir.compiler import MAX_OPS_PER_PROGRAM

    m = re.search(r"не более (\d+) операций", desc)
    assert m, "the program size cap must ship"
    assert int(m.group(1)) == MAX_OPS_PER_PROGRAM, (
        f"description says {m.group(1)}, compiler enforces {MAX_OPS_PER_PROGRAM}")
    serving.inject_revit_ir_schema(tools)
    assert len(tools) == 1, "injection must stay idempotent"
