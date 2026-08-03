"""Mock bridge server for testing — returns contract fixture responses."""

from __future__ import annotations

import json
import logging
from contextlib import asynccontextmanager
from pathlib import Path
from typing import Any, AsyncIterator

from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse

logger = logging.getLogger(__name__)

# Load fixtures from tests/contracts/bridge/
FIXTURES_DIR = Path(__file__).parent.parent.parent.parent / "tests" / "contracts" / "bridge"


def _load_fixture(name: str) -> dict[str, Any]:
    """Load a JSON fixture file."""
    path = FIXTURES_DIR / name
    if path.exists():
        return json.loads(path.read_text(encoding="utf-8"))
    raise FileNotFoundError(f"Fixture not found: {path}")


# Pre-load all response fixtures
_RESPONSES: dict[str, dict[str, Any]] = {}


def _ensure_loaded() -> None:
    if _RESPONSES:
        return
    fixture_map = {
        "ping": "ping_response.json",
        "context": "context_response.json",
        "execute": "execute_response_success.json",
        "select": "select_response.json",
        "highlight": "highlight_response.json",
    }
    for method, filename in fixture_map.items():
        try:
            _RESPONSES[method] = _load_fixture(filename)
        except FileNotFoundError:
            logger.warning("Fixture %s not found, skipping", filename)


@asynccontextmanager
async def _lifespan(app: FastAPI) -> AsyncIterator[None]:
    _ensure_loaded()
    yield


def create_mock_bridge_app() -> FastAPI:
    """Create a FastAPI app that mimics the C# bridge for testing."""
    app = FastAPI(title="Mock Revit Bridge", lifespan=_lifespan)

    @app.post("/rpc")
    async def rpc_handler(request: Request) -> JSONResponse:
        body = await request.json()
        method = body.get("method", "")
        request_id = body.get("id", "unknown")

        _ensure_loaded()

        if method not in _RESPONSES:
            return JSONResponse(
                content={
                    "jsonrpc": "2.0",
                    "error": {
                        "code": -32601,
                        "message": f"Method not found: {method}",
                        "data": None,
                    },
                    "id": request_id,
                },
                status_code=200,
            )

        # Return fixture response but with the correct request id
        response = _RESPONSES[method].copy()
        response["id"] = request_id
        return JSONResponse(content=response)

    return app
