"""Tests for HttpCompileClient."""
from __future__ import annotations
import json as _json
import pytest
import httpx

from kukai.modeling.bridge.compile_client import HttpCompileClient


@pytest.fixture
def mock_transport():
    """An httpx MockTransport simulating the compile-service (post-Phase 1 schema)."""
    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path == "/compile":
            body = request.read().decode()
            assert "revitVersion" in body, "compile_client must send revitVersion"
            if "syntax error here" in body:
                return httpx.Response(200, json={
                    "success": False,
                    "errors": [{"code": "CS1002", "message": "; expected", "line": 1, "column": 8}],
                })
            return httpx.Response(200, json={"success": True, "assembly_id": "asm_abc", "errors": []})
        if request.url.path == "/health":
            return httpx.Response(200, json={"status": "ready", "versions": ["2026"]})
        return httpx.Response(404)
    return httpx.MockTransport(handler)


@pytest.mark.asyncio
async def test_compile_success(mock_transport):
    client = HttpCompileClient(
        base_url="http://localhost:52412",
        transport=mock_transport,
    )
    result = await client.compile("// valid c#")
    assert result.success is True
    assert result.assembly_id == "asm_abc"
    assert result.error is None


@pytest.mark.asyncio
async def test_compile_failure(mock_transport):
    client = HttpCompileClient(
        base_url="http://localhost:52412",
        transport=mock_transport,
    )
    result = await client.compile("syntax error here")
    assert result.success is False
    assert len(result.errors) == 1
    assert result.errors[0].code == "CS1002"
    assert "expected" in result.errors[0].message
    assert result.error and "expected" in result.error  # back-compat @property
    assert result.assembly_id is None


@pytest.mark.asyncio
async def test_health(mock_transport):
    client = HttpCompileClient(
        base_url="http://localhost:52412",
        transport=mock_transport,
    )
    assert await client.health() is True


@pytest.mark.asyncio
@pytest.mark.tier0
async def test_health_logs_warning_on_malformed_json(caplog):
    """Audit N10: ValueError (malformed JSON) → WARNING log; HTTPError → silent."""
    import logging

    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path == "/health":
            # 200 OK with body that isn't valid JSON (truncated, corrupted, etc.)
            return httpx.Response(
                200, content=b"not actually json", headers={"content-type": "application/json"},
            )
        return httpx.Response(404)

    client = HttpCompileClient(
        base_url="http://localhost:52412",
        transport=httpx.MockTransport(handler),
    )
    with caplog.at_level(logging.WARNING, logger="kukai.modeling.bridge.compile_client"):
        result = await client.health()
    assert result is False
    # WARNING must be emitted distinguishing this from a simple "service down".
    warning_msgs = [r.getMessage() for r in caplog.records if r.levelno >= logging.WARNING]
    assert any("non-JSON" in m for m in warning_msgs), warning_msgs


@pytest.mark.asyncio
@pytest.mark.tier0
async def test_health_silent_on_http_error(caplog):
    """Audit N10: HTTPError remains silent (operator already knows service is down)."""
    import logging

    def handler(request: httpx.Request) -> httpx.Response:
        # Simulate the service returning 500 — health check fails but it's not corruption.
        return httpx.Response(500)

    client = HttpCompileClient(
        base_url="http://localhost:52412",
        transport=httpx.MockTransport(handler),
    )
    with caplog.at_level(logging.WARNING, logger="kukai.modeling.bridge.compile_client"):
        result = await client.health()
    assert result is False
    # No WARNING should be logged for an ordinary HTTP error.
    assert not any(
        r.name == "kukai.modeling.bridge.compile_client" and r.levelno >= logging.WARNING
        for r in caplog.records
    )


@pytest.mark.asyncio
async def test_compile_sends_revit_version():
    """Service requires revitVersion; client must include it in the JSON body."""
    captured: dict = {}

    def handler(request: httpx.Request) -> httpx.Response:
        captured["body"] = _json.loads(request.read().decode())
        return httpx.Response(200, json={"success": True, "errors": []})

    client = HttpCompileClient(
        base_url="http://localhost:52412",
        transport=httpx.MockTransport(handler),
    )
    result = await client.compile("// any", revit_version="2026")
    assert result.success is True
    assert captured["body"] == {"code": "// any", "revitVersion": "2026"}


@pytest.mark.asyncio
async def test_compile_parses_errors_array():
    """Service returns {success: False, errors: [{code, message, line}]}."""

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json={
            "success": False,
            "errors": [
                {"code": "CS1002", "message": "; expected", "line": 7},
                {"code": "CS0103", "message": "name 'doc' does not exist", "line": 9},
            ],
        })

    client = HttpCompileClient(
        base_url="http://localhost:52412",
        transport=httpx.MockTransport(handler),
    )
    result = await client.compile("syntax err", revit_version="2026")
    assert result.success is False
    # Existing schema uses errors: list[CompileError] with a .error @property
    # that returns the first message. Verify both diagnostics are surfaced.
    assert len(result.errors) == 2
    codes = {e.code for e in result.errors}
    assert codes == {"CS1002", "CS0103"}
    assert any("; expected" in e.message for e in result.errors)
    assert any("name 'doc'" in e.message for e in result.errors)
    # The .error backward-compat property returns the first message.
    assert result.error is not None
    assert "; expected" in result.error
