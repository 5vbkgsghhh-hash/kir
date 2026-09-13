"""A schema failure is not a rollback, and neither MCP output carries NaN."""
import asyncio
import json

import pytest

from kir import wire_json
from kir.mcp import server


@pytest.mark.parametrize("bad", [float("nan"), float("inf"), -float("inf"), object()])
def test_result_failure_preserves_correlation_without_claiming_rollback(monkeypatch, bad):
    calls = []

    def done(args):
        calls.append(args)
        return {"ok": True, "operation_id": "op-123", "effect": "committed", "measurement": bad}

    monkeypatch.setitem(server._DOORS, "kir_write", done)
    result, crashed = asyncio.run(server.dispatch("kir_write", {"operation_id": "op-123"}))
    assert len(calls) == 1 and crashed is True
    assert result["state"] == "response_schema_failure"
    assert result["effect"] == "unknown" and result["retry_safe"] is False
    assert result["context"]["operation_id"] == "op-123"
    assert result["reported_result"]["effect"] == "committed"
    assert result["reported_result_is_partial"] is True
    assert result["invalid_paths"][0]["path"] == "/measurement"
    wire_json.encode(result)


@pytest.mark.parametrize("bad", [float("nan"), float("inf"), -float("inf")])
def test_non_finite_input_is_refused_before_the_tool(monkeypatch, bad):
    calls = []
    monkeypatch.setitem(server._DOORS, "kir_write", lambda args: calls.append(args) or {})
    result, crashed = asyncio.run(server.dispatch("kir_write", {"value": bad}))
    assert not crashed and result["effect"] == "none" and result["wrote_nothing"] is True
    assert result["err"]["code"] == "invalid_json_input"
    assert calls == []


@pytest.mark.parametrize("message", ["reply failed after effect", "\ud800"])
def test_tool_exception_after_an_effect_does_not_authorize_a_retry(monkeypatch, tmp_path, message):
    target = tmp_path / "effect"
    calls = []

    def done(args):
        calls.append(args)
        target.write_text("committed")
        raise RuntimeError(message)

    monkeypatch.setitem(server._DOORS, "kir_write", done)
    result, crashed = asyncio.run(server.dispatch("kir_write", {"operation_id": "once"}))
    assert crashed is True and len(calls) == 1 and target.read_text() == "committed"
    assert result["effect"] == "unknown" and result["retry_safe"] is False
    assert result["wrote_nothing"] is False and result["context"]["operation_id"] == "once"
    wire_json.encode(result)


def test_an_exception_is_not_formatted_by_calling_user_code(monkeypatch):
    class UnprintableError(Exception):
        def __str__(self):
            raise AssertionError("do not call custom exception formatting")

    def done(args):
        raise UnprintableError()

    monkeypatch.setitem(server._DOORS, "kir_write", done)
    result, crashed = asyncio.run(server.dispatch("kir_write", {"operation_id": "once"}))
    assert crashed and result["context"]["operation_id"] == "once"
    wire_json.encode(result)


def test_partial_diagnostic_is_bounded_and_does_not_call_object_repr():
    class Secret:
        def __repr__(self):
            raise AssertionError("repr is not diagnostic permission")

    cycle = [Secret()]
    cycle.append(cycle)
    value = {"bad": cycle, "large_integer": 1 << 20000,
             "lots": ["x" * 10000] * 10000}
    result = wire_json.failure(value, known_effect="unknown", context={"operation_id": "known"})
    assert result["reported_result_truncated"] is True
    assert len(wire_json.encode(result)) < 18000
    assert any(row["reason"] == "cyclic_value" for row in result["invalid_paths"])


def test_real_sdk_http_carries_the_same_finite_failure_in_both_channels(monkeypatch):
    pytest.importorskip("mcp_types")
    from kir.mcp.tests.http_client import call
    calls = []

    def done(args):
        calls.append(args)
        return {"ok": True, "operation_id": "once", "effect": "committed", "area": float("nan")}

    monkeypatch.setitem(server._DOORS, "kir_spec", done)
    app = server.build_server().streamable_http_app(json_response=True)
    response = asyncio.run(call(app, "kir_spec", {}))
    assert response.status_code == 200, response.text
    body = json.loads(response.text, parse_constant=wire_json.reject_constant)["result"]
    assert len(calls) == 1
    assert body["isError"] is True
    assert json.loads(body["content"][0]["text"]) == body["structuredContent"]
    assert body["structuredContent"]["context"]["operation_id"] == "once"
    assert body["structuredContent"]["retry_safe"] is False


@pytest.mark.parametrize("key", [lambda i: (i,), lambda i: "x" * 129 + str(i),
                                  lambda i: "\ud800" + str(i)])
def test_invalid_dictionary_keys_also_spend_the_diagnostic_budget(key):
    value = {key(i): 0 for i in range(1000)}
    value["past_the_budget"] = "must not be visited"
    result = wire_json.failure(value, known_effect="unknown")
    assert result["reported_result"] == {}
    assert result["reported_result_truncated"] is True
    assert len(result["invalid_paths"]) <= 16
    wire_json.encode(result)


def test_real_sdk_http_non_finite_input_never_calls_the_tool(monkeypatch):
    pytest.importorskip("mcp_types")
    from kir.mcp.tests.http_client import call
    calls = []
    monkeypatch.setitem(server._DOORS, "kir_spec", lambda args: calls.append(args) or {})
    app = server.build_server().streamable_http_app(json_response=True)
    response = asyncio.run(call(app, "kir_spec", {"unknown": float("nan")}))
    assert response.status_code == 200, response.text
    body = json.loads(response.text, parse_constant=wire_json.reject_constant)["result"]
    assert body["structuredContent"]["err"]["code"] == "invalid_json_input"
    assert calls == []
