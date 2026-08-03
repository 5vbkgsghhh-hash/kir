"""Tests for bridge client — validates against contract fixtures."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import httpx
import pytest
import pytest_asyncio

from kukai.bridge.client import BridgeClient
from kukai.bridge.models import (
    BridgeError,
    BridgeRequest,
    BridgeResponse,
    ContextResult,
    ExecuteResult,
    ExportViewResult,
    HighlightResult,
    ImportCadResult,
    PingResult,
    SelectResult,
)

FIXTURES_DIR = Path(__file__).parent.parent.parent / "tests" / "contracts" / "bridge"


def load_fixture(name: str) -> dict[str, Any]:
    path = FIXTURES_DIR / name
    return json.loads(path.read_text(encoding="utf-8"))


class MockTransport(httpx.AsyncBaseTransport):
    """Mock transport that returns fixture responses."""

    def __init__(self, responses: dict[str, dict[str, Any]]):
        self._responses = responses

    async def handle_async_request(self, request: httpx.Request) -> httpx.Response:
        body = json.loads(request.content)
        method = body.get("method", "")
        request_id = body.get("id", "")

        if method in self._responses:
            resp = self._responses[method].copy()
            resp["id"] = request_id
            return httpx.Response(200, json=resp)
        else:
            return httpx.Response(200, json={
                "jsonrpc": "2.0",
                "error": {"code": -32601, "message": f"Method not found: {method}"},
                "id": request_id,
            })


@pytest_asyncio.fixture
async def mock_bridge() -> BridgeClient:
    """Create a bridge client with mock transport returning fixture data."""
    responses = {
        "ping": load_fixture("ping_response.json"),
        "context": load_fixture("context_response.json"),
        "execute": load_fixture("execute_response_success.json"),
        "select": load_fixture("select_response.json"),
        "highlight": load_fixture("highlight_response.json"),
        "export_view": load_fixture("export_view_response.json"),
        "import_cad": load_fixture("import_cad_response.json"),
    }

    client = BridgeClient("http://localhost:52410", timeout=5.0)
    # Replace the internal httpx client with a mock
    client._client = httpx.AsyncClient(
        base_url="http://localhost:52410",
        transport=MockTransport(responses),
    )
    return client


@pytest.mark.asyncio
async def test_ping(mock_bridge: BridgeClient) -> None:
    """Ping should return fixture data and mark connected."""
    result = await mock_bridge.ping()
    assert isinstance(result, PingResult)
    assert result.status == "ok"
    assert result.revit_version == "2025"
    assert result.has_document is True
    assert result.document_name == "MyProject.rvt"
    assert result.bridge_version == "1.0.0"
    assert mock_bridge.connected is True


@pytest.mark.asyncio
async def test_context(mock_bridge: BridgeClient) -> None:
    """Context should return full model info from fixture."""
    result = await mock_bridge.context()
    assert isinstance(result, ContextResult)
    assert result.document.name == "MyProject.rvt"
    assert result.document.revit_version == "2025"
    assert len(result.categories) == 5
    assert result.categories[0].name == "Walls"
    assert result.categories[0].count == 347
    assert len(result.levels) == 3
    assert result.current_view.name == "Level 1 - Floor Plan"
    assert result.selection.count == 3
    assert result.warnings_count == 42


@pytest.mark.asyncio
async def test_execute(mock_bridge: BridgeClient) -> None:
    """Execute should return success result from fixture."""
    result = await mock_bridge.execute("var x = 1;")
    assert isinstance(result, ExecuteResult)
    assert result.success is True
    assert result.output == {"count": 347}
    assert result.execution_time_ms == 45


@pytest.mark.asyncio
async def test_select(mock_bridge: BridgeClient) -> None:
    """Select should return selected count from fixture."""
    result = await mock_bridge.select([1001, 1002, 1003, 1004])
    assert isinstance(result, SelectResult)
    assert result.selected_count == 4
    assert result.invalid_ids == []


@pytest.mark.asyncio
async def test_highlight(mock_bridge: BridgeClient) -> None:
    """Highlight should return highlighted count from fixture."""
    result = await mock_bridge.highlight([1001, 1002])
    assert isinstance(result, HighlightResult)
    assert result.highlighted_count == 2
    assert result.invalid_ids == []


@pytest.mark.asyncio
async def test_bridge_error_handling() -> None:
    """Bridge should raise BridgeError on error responses."""
    error_response = load_fixture("execute_response_validation_error.json")

    responses = {"execute": error_response}
    client = BridgeClient("http://localhost:52410")
    client._client = httpx.AsyncClient(
        base_url="http://localhost:52410",
        transport=MockTransport(responses),
    )

    with pytest.raises(BridgeError) as exc_info:
        await client.execute("File.Delete('x');")

    assert exc_info.value.code == -32001
    assert "validation" in exc_info.value.error_message.lower()


@pytest.mark.asyncio
async def test_compile_error() -> None:
    """Bridge should raise BridgeError on compilation error."""
    error_response = load_fixture("execute_response_compile_error.json")

    responses = {"execute": error_response}
    client = BridgeClient("http://localhost:52410")
    client._client = httpx.AsyncClient(
        base_url="http://localhost:52410",
        transport=MockTransport(responses),
    )

    with pytest.raises(BridgeError) as exc_info:
        await client.execute("invalid code")

    assert exc_info.value.code == -32002
    assert "compilation" in exc_info.value.error_message.lower()


@pytest.mark.asyncio
async def test_runtime_error() -> None:
    """Bridge should raise BridgeError on runtime error."""
    error_response = load_fixture("execute_response_runtime_error.json")

    responses = {"execute": error_response}
    client = BridgeClient("http://localhost:52410")
    client._client = httpx.AsyncClient(
        base_url="http://localhost:52410",
        transport=MockTransport(responses),
    )

    with pytest.raises(BridgeError) as exc_info:
        await client.execute("bad code")

    assert exc_info.value.code == -32003
    assert "execution" in exc_info.value.error_message.lower()


@pytest.mark.asyncio
async def test_check_connection_success(mock_bridge: BridgeClient) -> None:
    """check_connection should return True when ping succeeds."""
    result = await mock_bridge.check_connection()
    assert result is True
    assert mock_bridge.connected is True


@pytest.mark.asyncio
async def test_request_model() -> None:
    """BridgeRequest should produce valid JSON-RPC."""
    req = BridgeRequest(method="ping", params={}, id="test-123")
    d = req.model_dump()
    assert d["jsonrpc"] == "2.0"
    assert d["method"] == "ping"
    assert d["id"] == "test-123"


@pytest.mark.asyncio
async def test_response_model() -> None:
    """BridgeResponse should parse fixture data correctly."""
    fixture = load_fixture("ping_response.json")
    resp = BridgeResponse.model_validate(fixture)
    assert resp.is_error is False
    assert resp.result is not None
    assert resp.result["status"] == "ok"


@pytest.mark.asyncio
async def test_error_response_model() -> None:
    """BridgeResponse should identify error responses."""
    fixture = load_fixture("error_no_document.json")
    resp = BridgeResponse.model_validate(fixture)
    assert resp.is_error is True
    assert resp.error is not None
    assert resp.error.code == -32005


@pytest.mark.asyncio
async def test_export_view_success(mock_bridge: BridgeClient) -> None:
    """export_view should return file path and dimensions from fixture."""
    result = await mock_bridge.export_view("test.png", "png")
    assert isinstance(result, ExportViewResult)
    assert result.success is True
    assert result.file_path.endswith("kukai_export.png")
    assert result.format == "png"
    assert result.width == 1920
    assert result.height == 1080


@pytest.mark.asyncio
async def test_import_cad_success(mock_bridge: BridgeClient) -> None:
    """import_cad should return element_id from fixture."""
    result = await mock_bridge.import_cad("C:\\Users\\user\\Documents\\floorplan.dwg")
    assert isinstance(result, ImportCadResult)
    assert result.success is True
    assert result.element_id == 98765
    assert result.message == "CAD file imported successfully"


@pytest.mark.asyncio
async def test_import_cad_file_not_found() -> None:
    """import_cad should raise BridgeError when bridge returns an error."""
    error_response = {
        "jsonrpc": "2.0",
        "error": {
            "code": -32006,
            "message": "File not found: C:\\nonexistent\\file.dwg",
        },
        "id": "test-id",
    }

    responses = {"import_cad": error_response}
    client = BridgeClient("http://localhost:52410")
    client._client = httpx.AsyncClient(
        base_url="http://localhost:52410",
        transport=MockTransport(responses),
    )

    with pytest.raises(BridgeError) as exc_info:
        await client.import_cad("C:\\nonexistent\\file.dwg")

    assert exc_info.value.code == -32006
    assert "not found" in exc_info.value.error_message.lower()
