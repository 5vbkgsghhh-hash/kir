"""HTTP client for the C# Revit bridge (BRIDGE_PROTOCOL.md)."""

from __future__ import annotations

import asyncio
import logging
import uuid
from typing import Any, Optional

import httpx

from kukai.bridge.models import (
    BridgeError,
    BridgeRequest,
    BridgeResponse,
    ContextResult,
    ExecuteResult,
    ExportViewResult,
    FamilyPassport,
    HighlightResult,
    ImportCadResult,
    PingResult,
    SelectResult,
)

logger = logging.getLogger(__name__)


class BridgeClient:
    """Async HTTP client that talks to the Revit bridge via JSON-RPC."""

    def __init__(self, base_url: str, timeout: float = 5.0, execute_timeout: float = 30.0):
        self._base_url = base_url.rstrip("/")
        self._timeout = timeout
        self._execute_timeout = execute_timeout
        self._connected = False
        self._last_ping: Optional[PingResult] = None
        self._client: Optional[httpx.AsyncClient] = None

    async def _get_client(self) -> httpx.AsyncClient:
        if self._client is None or self._client.is_closed:
            self._client = httpx.AsyncClient(
                base_url=self._base_url,
                # connect capped at 5s: if the Revit plugin is down, fail fast
                # instead of hanging up to bridge_timeout (900s). read stays
                # large for long-running Revit operations.
                timeout=httpx.Timeout(self._timeout, connect=5.0, read=self._execute_timeout),
                headers={"Content-Type": "application/json"},
            )
        return self._client

    async def close(self) -> None:
        if self._client and not self._client.is_closed:
            await self._client.aclose()
            self._client = None

    def _make_request(self, method: str, params: dict[str, Any] | None = None) -> BridgeRequest:
        return BridgeRequest(
            method=method,
            params=params or {},
            id=str(uuid.uuid4()),
        )

    async def _call(self, method: str, params: dict[str, Any] | None = None,
                    timeout: float | None = None) -> dict[str, Any]:
        """Send a JSON-RPC request and return the result dict."""
        req = self._make_request(method, params)
        client = await self._get_client()

        read_t = timeout or self._timeout
        try:
            resp = await client.post(
                "/rpc",
                json=req.model_dump(),
                # connect stays small so a closed Revit plugin fails in ~5s;
                # read uses the (possibly large) per-call timeout for long ops.
                timeout=httpx.Timeout(read_t, connect=min(5.0, read_t)),
            )
            resp.raise_for_status()
            body = resp.json()
        except (httpx.ConnectError, httpx.ConnectTimeout):
            # Revit plugin not listening — surface a clean, user-facing message.
            # This string reaches the LLM tool-result and the end user, so keep
            # it human and actionable rather than a raw httpx error.
            logger.warning("Bridge not reachable on method=%s (Revit plugin not connected)", method)
            raise BridgeError(-32010, "Revit не подключён — откройте плагин KUKAI в Revit")
        except httpx.TimeoutException:
            logger.warning("Bridge timeout on method=%s", method)
            raise BridgeError(-32004, f"Bridge timeout on {method}")
        except httpx.HTTPError as e:
            logger.error("Bridge HTTP error on method=%s: %s", method, e)
            raise BridgeError(-32010, f"Bridge HTTP error: {e}")

        bridge_resp = BridgeResponse.model_validate(body)

        if bridge_resp.is_error:
            err = bridge_resp.error
            assert err is not None
            raise BridgeError(err.code, err.message, err.data)

        return bridge_resp.result or {}

    # --- Public API ---

    @property
    def connected(self) -> bool:
        return self._connected

    @property
    def last_ping(self) -> Optional[PingResult]:
        return self._last_ping

    async def ping(self) -> PingResult:
        """Health check — returns bridge status."""
        result = await self._call("ping")
        ping_result = PingResult.model_validate(result)
        self._connected = True
        self._last_ping = ping_result
        return ping_result

    async def context(self) -> ContextResult:
        """Get model context for LLM system prompt."""
        result = await self._call("context", timeout=10.0)
        return ContextResult.model_validate(result)

    async def family_inspect(self) -> FamilyPassport:
        """Rich read-only inventory of the active family document.

        Used by the `inspect_family` LLM tool in family-editor mode. Returns
        a snapshot of category/parameters/types/solids/refs/labeled dims/
        materials so Gemini can compose tool calls aware of current state.

        Safe on family docs (no project-only API access — same defensive
        try/catch pattern as Collect() V1).
        """
        # Slightly longer timeout — passport walks several collectors
        result = await self._call("family_inspect", timeout=15.0)
        return FamilyPassport.model_validate(result)

    async def execute(self, code: str, timeout_ms: int = 30000) -> ExecuteResult:
        """Execute C# code inside Revit."""
        result = await self._call(
            "execute",
            {"code": code, "timeout_ms": timeout_ms},
            timeout=max(timeout_ms / 1000 + 5, self._execute_timeout),
        )
        return ExecuteResult.model_validate(result)

    async def select(self, element_ids: list[int]) -> SelectResult:
        """Select elements in Revit viewport."""
        result = await self._call("select", {"element_ids": element_ids})
        return SelectResult.model_validate(result)

    async def highlight(
        self,
        element_ids: list[int],
        color: dict[str, int] | None = None,
        clear_previous: bool = True,
    ) -> HighlightResult:
        """Highlight elements with color override."""
        params: dict[str, Any] = {
            "element_ids": element_ids,
            "color": color or {"r": 255, "g": 0, "b": 0},
            "clear_previous": clear_previous,
        }
        result = await self._call("highlight", params)
        return HighlightResult.model_validate(result)

    async def export_view(self, filename: str = "kukai_export.png", format: str = "png") -> ExportViewResult:
        """Export the current Revit view to an image file."""
        result = await self._call("export_view", {"filename": filename, "format": format})
        return ExportViewResult.model_validate(result)

    async def import_cad(self, file_path: str) -> ImportCadResult:
        """Import a CAD file (DWG/DXF) into the current Revit document."""
        result = await self._call("import_cad", {"file_path": file_path})
        return ImportCadResult.model_validate(result)

    # --- Heartbeat ---

    async def check_connection(self) -> bool:
        """Attempt a ping; update connected status. Returns True if connected."""
        try:
            await self.ping()
            self._connected = True
            return True
        except (BridgeError, Exception):
            self._connected = False
            self._last_ping = None
            return False
