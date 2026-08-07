"""Client for the server-side Roslyn compile service."""

import asyncio
import logging
import os
from dataclasses import dataclass, field
from typing import Optional

import httpx

from kukai.ir.compile_receipt import CompileReceipt
from kukai.ir.emitted_artifact import EmittedArtifact

logger = logging.getLogger(__name__)

_COMPILE_REQUEST_SCHEMA = "kir-compile-request/1"
_COMPILE_RESPONSE_SCHEMA = "kir-compile-response/1"
_COMPILE_RESPONSE_FIELDS = frozenset({
    "schema",
    "success",
    "errors",
    "receipt",
})
_COMPILE_ERROR_FIELDS = frozenset({"code", "message", "line", "column"})

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


@dataclass(frozen=True, slots=True)
class CompileError:
    code: str       # e.g. "CS0246"
    message: str    # e.g. "The type 'Foo' could not be found"
    line: int
    column: int


@dataclass
class CompileResult:
    success: bool
    errors: list[CompileError] = field(default_factory=list)


@dataclass(frozen=True, slots=True)
class ArtifactCompileResult:
    """Strict result bound to one immutable emitted artifact."""

    success: bool
    errors: tuple[CompileError, ...]
    receipt: CompileReceipt | None

    def __post_init__(self) -> None:
        if type(self.success) is not bool:
            raise TypeError("artifact compile success must be bool")
        if (not isinstance(self.errors, tuple)
                or any(not isinstance(error, CompileError)
                       for error in self.errors)):
            raise TypeError("artifact compile errors must be a typed tuple")
        if self.receipt is not None and not isinstance(
            self.receipt, CompileReceipt
        ):
            raise TypeError("artifact compile receipt must be typed or None")
        if self.success:
            if self.receipt is None or self.errors:
                raise ValueError(
                    "successful artifact compile needs a receipt and no errors"
                )
        else:
            if self.receipt is not None:
                raise ValueError("failed artifact compile cannot carry a receipt")
            if not self.errors:
                raise ValueError(
                    "failed artifact compile needs at least one diagnostic")


def _exact_object(
    value: object,
    *,
    fields: frozenset[str],
    path: str,
) -> dict:
    if type(value) is not dict:
        raise ValueError(f"{path} must be an object")
    if frozenset(value) != fields:
        raise ValueError(f"{path} fields mismatch")
    return value


def _parse_compile_errors(value: object) -> tuple[CompileError, ...]:
    if type(value) is not list:
        raise ValueError("response.errors must be an array")

    parsed: list[CompileError] = []
    for index, item in enumerate(value):
        error = _exact_object(
            item,
            fields=_COMPILE_ERROR_FIELDS,
            path=f"response.errors[{index}]",
        )
        if type(error["code"]) is not str:
            raise ValueError(f"response.errors[{index}].code must be string")
        if type(error["message"]) is not str:
            raise ValueError(
                f"response.errors[{index}].message must be string")
        if type(error["line"]) is not int:
            raise ValueError(
                f"response.errors[{index}].line must be integer")
        if type(error["column"]) is not int:
            raise ValueError(
                f"response.errors[{index}].column must be integer")
        parsed.append(CompileError(
            code=error["code"],
            message=error["message"],
            line=error["line"],
            column=error["column"],
        ))
    return tuple(parsed)


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

    async def check_artifact(
        self,
        artifact: EmittedArtifact,
    ) -> Optional[ArtifactCompileResult]:
        """Compile one emitted artifact through the strict receipt protocol.

        ``None`` means that no trustworthy protocol result was obtained.  A
        normal Roslyn rejection is instead returned as a typed unsuccessful
        result, so callers cannot confuse compile errors with an unavailable or
        malformed service.
        """
        try:
            expected = CompileReceipt.expected_for(artifact)
            client = await self._get_client()
            response = await client.post(
                f"{self._base_url}/compile-receipt/v1",
                json={
                    "schema": _COMPILE_REQUEST_SCHEMA,
                    "source": artifact.source,
                    "artifact": expected.artifact.to_dict(),
                    "compile_unit": expected.compile_unit.to_dict(),
                    "target": expected.target.to_dict(),
                },
            )
            if response.status_code != 200:
                logger.warning(
                    "Strict compile service returned %d",
                    response.status_code,
                )
                self._available = False
                return None

            data = _exact_object(
                response.json(),
                fields=_COMPILE_RESPONSE_FIELDS,
                path="response",
            )
            if type(data["schema"]) is not str:
                raise ValueError("response.schema must be string")
            if data["schema"] != _COMPILE_RESPONSE_SCHEMA:
                raise ValueError("unsupported strict compile response schema")
            if type(data["success"]) is not bool:
                raise ValueError("response.success must be bool")
            errors = _parse_compile_errors(data["errors"])

            raw_receipt = data["receipt"]
            if raw_receipt is not None and type(raw_receipt) is not dict:
                raise ValueError("response.receipt must be an object or null")

            receipt: CompileReceipt | None = None
            if data["success"]:
                if raw_receipt is None:
                    raise ValueError(
                        "successful strict compile must carry a receipt")
                receipt = CompileReceipt.from_dict(raw_receipt)
                receipt.verified_compile_unit(artifact)
                if receipt != expected:
                    raise ValueError(
                        "strict compile receipt differs from expected evidence")
            elif raw_receipt is not None:
                raise ValueError("failed strict compile cannot carry a receipt")

            result = ArtifactCompileResult(
                success=data["success"],
                errors=errors,
                receipt=receipt,
            )
            self._available = True
            return result
        except Exception as exc:
            logger.debug("Strict compile service unavailable: %s", exc)
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
