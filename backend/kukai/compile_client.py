"""Client for the server-side Roslyn compile service."""

import asyncio
import logging
import os
from dataclasses import dataclass, field
from typing import Optional

import httpx

logger = logging.getLogger(__name__)

_ALL_SHIPPED_REVIT_VERSIONS = frozenset(
    {"2021", "2022", "2023", "2024", "2025", "2026"}
)


def _resolve_required_revit_versions() -> "frozenset[str]":
    """Required Revit versions for the compile gate.

    Mirrors ``RoslynCompiler.ResolveRequiredVersions``: the *required* subset is
    configurable via ``KUKAI_COMPILE_REQUIRED_VERSIONS`` (comma-separated, e.g.
    ``"2025,2026"``).  The C# gate and this Python readiness check read the SAME
    raw env var with identical rules so they can never drift.  Unset/empty/
    malformed → the full shipped matrix (fail-closed: an empty required set would
    mean "require nothing").
    """
    raw = os.getenv("KUKAI_COMPILE_REQUIRED_VERSIONS")
    if not raw or not raw.strip():
        return _ALL_SHIPPED_REVIT_VERSIONS
    parsed = {
        tok
        for tok in (part.strip() for part in raw.split(","))
        if len(tok) == 4 and tok.isdigit()
    }
    return frozenset(parsed) if parsed else _ALL_SHIPPED_REVIT_VERSIONS


_REQUIRED_REVIT_VERSIONS = _resolve_required_revit_versions()


@dataclass
class CompileError:
    code: str       # e.g. "CS0246"
    message: str    # e.g. "The type 'Foo' could not be found"
    line: int
    column: int


@dataclass
class CompileResult:
    success: bool
    errors: list[CompileError] = field(default_factory=list)


class CompileClient:
    """Client for server-side Roslyn compile service."""

    def __init__(self, base_url: str = "http://localhost:52412", timeout: float = 15.0):
        self._base_url = base_url.rstrip("/")
        self._timeout = timeout
        self._available = False
        self._client: Optional[httpx.AsyncClient] = None

    async def _get_client(self) -> httpx.AsyncClient:
        if self._client is None or self._client.is_closed:
            self._client = httpx.AsyncClient(timeout=httpx.Timeout(self._timeout))
        return self._client

    async def check(self, wrapped_code: str, revit_version: str) -> Optional[CompileResult]:
        """Compile code and return result. Returns None if service unavailable."""
        try:
            client = await self._get_client()
            resp = await client.post(
                f"{self._base_url}/compile",
                json={"code": wrapped_code, "revitVersion": revit_version},
            )
            if resp.status_code != 200:
                logger.warning("Compile service returned %d", resp.status_code)
                return None
            data = resp.json()
            errors = [
                CompileError(
                    code=e.get("code", ""),
                    message=e.get("message", ""),
                    line=e.get("line", 0),
                    column=e.get("column", 0),
                )
                for e in data.get("errors", [])
            ]
            result = CompileResult(success=data.get("success", False), errors=errors)
            self._available = True
            return result
        except Exception as e:
            logger.debug("Compile service unavailable: %s", e)
            self._available = False
            return None

    async def health(self) -> bool:
        """Return true only for a complete six-version reference matrix.

        ``/health`` is deliberately a liveness endpoint and returns HTTP 200
        even when one or more Revit reference sets are absent.  Treating that
        response as gate readiness allowed a nominal ``6/6`` run to start on a
        partially provisioned service.  ``/ready`` is the compile service's
        fail-closed contract; validate its advertised matrix as well as its
        status so a malformed or stale deployment cannot be mistaken for the
        six-version gate.
        """
        try:
            client = await self._get_client()
            resp = await client.get(f"{self._base_url}/ready")
            if resp.status_code != 200:
                self._available = False
                return False
            data = resp.json()
            versions = data.get("versions")
            required = data.get("requiredVersions")
            missing = data.get("missingVersions")
            self._available = (
                data.get("status") == "ready"
                and isinstance(versions, list)
                and len(versions) == len(_REQUIRED_REVIT_VERSIONS)
                and all(isinstance(item, str) for item in versions)
                and set(versions) == _REQUIRED_REVIT_VERSIONS
                and isinstance(required, list)
                and len(required) == len(_REQUIRED_REVIT_VERSIONS)
                and all(isinstance(item, str) for item in required)
                and set(required) == _REQUIRED_REVIT_VERSIONS
                and missing == []
            )
            return self._available
        except Exception:
            self._available = False
            return False

    @property
    def available(self) -> bool:
        return self._available

    async def close(self) -> None:
        if self._client and not self._client.is_closed:
            await self._client.aclose()
