"""A protocol string 'false' must never become permission to write a model."""
import asyncio

import pytest

from kir.mcp import live, server


@pytest.mark.parametrize("value", ["false", "true", 0, 1, [], {}])
def test_direct_write_rejects_invalid_confirmation_before_resolving_a_host(monkeypatch, value):
    def forbidden():
        pytest.fail("invalid confirmation reached the host seam")

    monkeypatch.setenv(live.WRITE_FLAG, "on")
    monkeypatch.setattr(live, "_transport", forbidden)
    response = asyncio.run(live.write_program({}, confirmed=value, state={}))
    assert response["ok"] is False and response["err"]["code"] == "confirmation_type"
    assert response["wrote_nothing"] is True and response["effect"] == "none"


@pytest.mark.parametrize("content", [{"confirm": "false"}, {"confirm": "true"},
                                      {"confirm": 0}, {"confirm": 1}, {}])
def test_sdk_accepted_content_is_validated_against_the_boolean_question(monkeypatch, content):
    pytest.importorskip("mcp_types")
    from kir.mcp.tests.http_client import call
    called = []

    def fake_write(args, **kwargs):
        called.append(kwargs)
        return {"ok": True}

    monkeypatch.setitem(server._DOORS, "kir_write", fake_write)
    app = server.build_server().streamable_http_app(json_response=True)
    response = asyncio.run(call(app, "kir_write", {}, input_responses={
        "confirm": {"action": "accept", "content": content}}, request_state="{}"))
    assert response.status_code == 200, response.text
    payload = response.json()["result"]["structuredContent"]
    assert called == []
    assert payload["err"]["code"] == "confirmation_type"
    assert payload["effect"] == "none" and payload["wrote_nothing"] is True


@pytest.mark.parametrize("action,value,expected", [("accept", True, True),
                                                  ("accept", False, False),
                                                  ("decline", True, False),
                                                  ("cancel", True, False)])
def test_real_boolean_and_explicit_decline_keep_their_meaning(monkeypatch, action, value, expected):
    pytest.importorskip("mcp_types")
    from kir.mcp.tests.http_client import call
    called = []

    def fake_write(args, **kwargs):
        called.append(kwargs)
        return {"ok": True, "confirmed": kwargs["confirmed"]}

    monkeypatch.setitem(server._DOORS, "kir_write", fake_write)
    app = server.build_server().streamable_http_app(json_response=True)
    response = asyncio.run(call(app, "kir_write", {}, input_responses={
        "confirm": {"action": action, "content": {"confirm": value}}}, request_state="{}"))
    assert response.status_code == 200, response.text
    assert len(called) == 1 and called[0]["confirmed"] is expected
    assert response.json()["result"]["structuredContent"]["confirmed"] is expected
