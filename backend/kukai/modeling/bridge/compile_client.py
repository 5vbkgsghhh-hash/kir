"""HttpCompileClient — Python wrapper around the existing Roslyn compile-service.

Service: backend/compile-service/ on port 52412. We POST /compile with C# source
and receive { success, assembly_id | error }.
"""
from __future__ import annotations
import logging
import time
from typing import Any

import httpx

from kukai.modeling.schemas.execution import CompileError, CompileResult


logger = logging.getLogger(__name__)


class HttpCompileClient:
    """Async HTTP client for the local Roslyn compile-service.

    Default base URL is `http://localhost:52412` (canonical). Override via
    explicit `base_url` arg OR the `KUKAI_COMPILE_SERVICE_URL` env var —
    Wave 7.5 follow-up so dev environments where another service holds
    52412 can point tier1/tier3 tests at a different port without code
    changes.
    """

    def __init__(
        self,
        base_url: str | None = None,
        timeout_seconds: float = 30.0,
        transport: httpx.BaseTransport | None = None,
    ):
        if base_url is None:
            import os
            base_url = os.environ.get(
                "KUKAI_COMPILE_SERVICE_URL", "http://localhost:52412"
            )
        self._base_url = base_url.rstrip("/")
        self._timeout = timeout_seconds
        self._transport = transport
        # Wave 6B (Fix B#4): expose .calls so ForemanBudgetGuard._count can
        # observe per-phase invocations and trip caps in production. Mirrors
        # MockCompileClient.calls contract — append on entry to each
        # external-work method, before any await.
        self.calls: list[dict[str, Any]] = []

    def _client(self) -> httpx.AsyncClient:
        kwargs = {"base_url": self._base_url, "timeout": self._timeout}
        if self._transport is not None:
            kwargs["transport"] = self._transport
        return httpx.AsyncClient(**kwargs)

    async def compile(
        self,
        csharp_code: str,
        revit_version: str = "2026",
    ) -> CompileResult:
        """Send C# source to the compile-service. Returns CompileResult.

        Wire format (per Program.cs/CompileRequest):
            request:  { "code": str, "revitVersion": str }
            response: { "success": bool, "errors": [ {code, message, line, column} ] }
        """
        # Wave 6B (Fix B#4): record call BEFORE network I/O so BudgetGuard
        # counts attempts even if the request later raises (we did spend
        # the slot).
        self.calls.append({
            "method": "compile",
            "args_summary": f"revit={revit_version} code_len={len(csharp_code)}",
            "ts": time.monotonic(),
        })
        async with self._client() as c:
            resp = await c.post("/compile", json={
                "code": csharp_code,
                "revitVersion": revit_version,
            })
            resp.raise_for_status()
            data = resp.json()

        errors = [CompileError.model_validate(e) for e in data.get("errors", [])]
        return CompileResult(
            success=bool(data.get("success", False)),
            code=csharp_code if data.get("success") else None,
            assembly_id=data.get("assembly_id"),  # not returned by current server; kept for back-compat
            errors=errors,
        )

    async def health(self) -> bool:
        """Return True if the compile-service responds to /health.

        Audit N10: distinguish failure modes. HTTPError (service down, timeout,
        4xx/5xx) is silent — operator already knows. ValueError (malformed
        JSON from a responding service) is an unexpected protocol break worth
        a WARNING log because the cause is corruption, not absence.
        """
        # Wave 6B (Fix B#4): health probes count toward budget too —
        # a runaway health loop is the same retry-spiral pathology.
        self.calls.append({
            "method": "health",
            "args_summary": "",
            "ts": time.monotonic(),
        })
        try:
            async with self._client() as c:
                resp = await c.get("/health")
                resp.raise_for_status()
                data = resp.json()
            # C# server returns {"status": "ready", "versions": [...]}.
            return data.get("status") == "ready"
        except httpx.HTTPError:
            return False
        except ValueError as e:
            logger.warning(
                "compile-service /health returned non-JSON body (%s); reporting unhealthy",
                e,
            )
            return False
