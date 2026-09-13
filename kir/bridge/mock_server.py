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

#: The variable by which the test rig is referred to FROM OUTSIDE.
FIXTURES_ENV = "KIR_BRIDGE_FIXTURES"

#: 🔴 THERE WAS A FOUR-DEEP `.parent` FROM THIS FILE, AND THAT IS WORSE THAN
#: JUST WRONG. The bridge-contract fixtures (`tests/contracts/bridge`) live
#: in the OWNER's tree, not in the language package: they are ABSENT HERE BY
#: CONSTRUCTION, and no number of steps upward will find them. After the
#: split, counting gave `/opt/tests/contracts/bridge` — a path that exists
#: for no one — and the refusal printed THAT path, sending the reader off to
#: look for the bug in their own layout.
#:
#: Hence the kind of fix here is DIFFERENT from its neighbors in this wave:
#: not "reposition the anchor" but NAME THE ABSENCE. An instrument whose
#: action may not take place must have a separate LOUD outcome (form 34):
#: "there are no fixtures" and "the fixture did not fit" are different
#: facts, and they are fixed differently.
def fixtures_dir() -> Path | None:
    """The bridge-contract fixture directory named by the operator, or
    ``None``."""
    from kir import env
    named = (env.get(FIXTURES_ENV) or "").strip()
    return Path(named) if named else None


def fixtures_refusal() -> str | None:
    """WHY there are no fixtures — in words; ``None`` if the directory is
    in place."""
    root = fixtures_dir()
    if root is None:
        return (f"стенд моста не назван: {FIXTURES_ENV} не задана. Фикстуры "
                "контракта (`tests/contracts/bridge`) живут в дереве ХОЗЯИНА, "
                "а не в пакете языка — здесь их нет по построению. "
                f"СЛЕДУЮЩИЙ ХОД: задай {FIXTURES_ENV} каталогом фикстур.")
    if not root.is_dir():
        return (f"каталог фикстур не существует: {root}. "
                f"СЛЕДУЮЩИЙ ХОД: проверь {FIXTURES_ENV}.")
    return None


def _load_fixture(name: str) -> dict[str, Any]:
    """Load a JSON fixture file."""
    refusal = fixtures_refusal()
    if refusal is not None:
        raise FileNotFoundError(refusal)
    path = fixtures_dir() / name          # type: ignore[operator]
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
